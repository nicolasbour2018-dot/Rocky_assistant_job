# Rocky — comptes rendus consolidés du projet

Dernière consolidation : 13 août 2026  
Projet : Rocky Job Assistant  
Périmètre : travaux, audits, diagnostics et évolutions réalisés depuis la reprise du projet

> Ce document rassemble les comptes rendus successifs produits pendant le projet.
> Il est organisé chronologiquement, mais reformulé pour éviter les répétitions et
> refléter l’état effectivement vérifiable dans le dépôt. Les secrets, mots de passe
> et valeurs de clés API sont volontairement exclus.

## 1. Synthèse générale

Rocky est resté un monolithe modulaire Python/Streamlit avec une couche de données
SQLAlchemy et PostgreSQL en local. L’application conserve une table centrale
d’annonces, un cockpit unique et des modules métier distincts pour la collecte,
l’hydratation, le matching, les candidatures, les profils et les analyses ATS.

Les principaux chantiers ont été :

1. reprise et déploiement local de Rocky ;
2. cartographie de l’architecture et audit des connecteurs ;
3. conservation des annonces incomplètes et réenrichissement volontaire ;
4. intégration de TheirStack comme fallback d’enrichissement ;
5. comparaison de trois dashboards, puis convergence vers le cockpit V2 ;
6. amélioration des cartes, filtres, métriques, statuts et fiche annonce ;
7. évolution des tests ATS V1/V2 et création d’un banc de robustesse ATS V3 ;
8. gestion et enrichissement des compétences des profils ;
9. rattachement multi-profils sans duplication des annonces ;
10. actions groupées dans la file d’enrichissement ;
11. amélioration du monitoring des sources ;
12. collecte Indeed via TheirStack ;
13. diagnostic d’observabilité des 20 annonces Indeed non insérées.

État de validation à la fin de cette consolidation :

- 74 tests automatisés réussis ;
- cockpit Streamlit démarré localement ;
- PostgreSQL initialisé avec les migrations idempotentes prévues par les chantiers
  antérieurs ;
- appel réel Indeed/TheirStack validé avec un résultat plafonné ;
- aucun secret présent dans le code ou dans ce document.

## 2. Reprise du projet et déploiement local

### Objectif

Revenir sur Rocky, identifier son point d’entrée et permettre un accès local stable.

### Résultat

Un script de lancement détaché a été utilisé afin de démarrer Streamlit uniquement
sur l’interface locale du Mac :

```text
http://127.0.0.1:8501
```

Le processus, son PID et les journaux sont conservés dans `logs/`. Le serveur est
lancé avec `server.fileWatcherType=none`, ce qui implique un redémarrage explicite
après les modifications de code.

### Fichiers et commandes

- point d’entrée V2 : `dashboard/dashboard_v2.py` ;
- lancement : `scripts/start_local.py` ;
- journal Streamlit : `logs/rocky_streamlit.log` ;
- PID : `logs/rocky_streamlit.pid`.

Commande :

```bash
.venv/bin/python scripts/start_local.py
```

Contrôle de santé :

```bash
curl --fail --silent --show-error http://127.0.0.1:8501/_stcore/health
```

## 3. Architecture initiale de l’application

### Vue d’ensemble

```text
┌─────────────────────────────────────────────────────────┐
│                  Interface Streamlit                    │
│ cockpit · profils · monitoring · ATS · candidatures     │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                 Modules métier Rocky                    │
│ collecte · import · hydratation · matching · lettres    │
│ enrichissement · ATS · configuration                    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│             Repository SQLAlchemy central               │
│ annonces · profils · compétences · matchs · dossiers    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                PostgreSQL / SQLite HF                   │
└─────────────────────────────────────────────────────────┘
```

### Modules principaux

| Responsabilité | Emplacement |
| --- | --- |
| Navigation V2 | `dashboard/dashboard_v2.py` |
| Cockpit | `dashboard/dashboard_b.py` |
| Composants partagés | `dashboard/dashboard_common.py` |
| Configuration `.env` | `dashboard/rocky/config.py` |
| Connexion et initialisation | `dashboard/rocky/database.py` |
| Requêtes SQL | `dashboard/rocky/repository.py` |
| Modèles d’échange | `dashboard/rocky/models.py` |
| Connecteurs | `dashboard/rocky/sources/` |
| Orchestration de la veille | `dashboard/rocky/watch.py` |
| Hydratation/import URL | `dashboard/rocky/job_importer.py` |
| Matching déterministe | `dashboard/rocky/matching.py` |
| Réenrichissement | `dashboard/rocky/enrichment.py` |
| Client TheirStack | `dashboard/rocky/theirstack.py` |
| Lettres et dossiers | `dashboard/rocky/letters.py` |
| ATS V1/V2 | `dashboard/rocky/ats.py` |
| ATS V3 | `dashboard/rocky/ats_v3.py` |

### Principes conservés pendant le projet

- pas d’API REST ajoutée ;
- pas de n8n ;
- pas de nouvelle architecture agentique ;
- pas de repository pattern supplémentaire : le repository existant reste central ;
- un seul cockpit réutilisé ;
- une seule table centrale d’annonces ;
- séparation entre collecte, normalisation, hydratation, matching et stockage ;
- secrets lus uniquement depuis l’environnement.

## 4. Audit des connecteurs de sources

### Objectif de l’audit

Identifier pour chaque connecteur la source fonctionnelle, les fichiers concernés,
les endpoints, les champs récupérés, l’existence d’un détail officiel et la cause
des descriptions courtes.

### Tableau comparatif issu de l’audit

| Source | Connecteur | Recherche | Détail disponible | Description observée | Confiance |
| --- | --- | --- | --- | --- | --- |
| France Travail | `sources/france_travail.py` | API officielle Offres d’emploi v2 | la recherche fournit la description exploitable | généralement complète | OK sous réserve de credentials valides |
| Adzuna | `sources/adzuna.py` | API officielle Adzuna | aucun endpoint de détail supplémentaire intégré | champ `description`, parfois résumé | partiel |
| LinkedIn | `sources/linkedin.py` | endpoint public « guest jobs » | pas de détail fiable utilisé | carte publique, souvent courte | partiel / fragile |
| Indeed, état initial | ancien `sources/indeed.py` | HTML public Indeed | page protégée ou vérification navigateur | extrait de carte | fragile |
| Welcome to the Jungle | `sources/wttj.py` | API publique `/api/v3/public/jobs` | API publique de fiche organisation/job | détail récupérable | OK |
| Apec | `sources/apec.py` | webservice `rechercheOffre` | endpoint public de fiche dans `job_importer.py` | recherche souvent tronquée, détail plus complet | OK après hydratation, sinon partiel |
| Wellfound | `sources/wellfound.py` | pages publiques/état Next.js | données structurées dans la page | variable selon la publication | partiel |

### Endpoints relevés

- France Travail :
  `https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search` ;
- Adzuna :
  `https://api.adzuna.com/v1/api/jobs/{pays}/search/1` ;
- LinkedIn :
  `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` ;
- Welcome to the Jungle :
  `https://api.welcometothejungle.com/api/v3/public/jobs` ;
- Apec :
  `https://www.apec.fr/cms/webservices/rechercheOffre` ;
- détail Apec :
  `https://www.apec.fr/cms/webservices/offre/public` ;
- détail Welcome to the Jungle :
  `https://api.welcometothejungle.com/api/v1/organizations/.../jobs/...` ;
- Wellfound : pages publiques `https://wellfound.com/...`.

### Pourquoi certaines annonces n’avaient qu’une short description

Les connecteurs de recherche ne renvoient pas tous la fiche complète :

- certaines plateformes n’exposent qu’une carte ou un extrait ;
- Apec peut terminer un aperçu par `...` ou `…` ;
- LinkedIn et l’ancien connecteur Indeed sont limités par les accès publics ;
- le champ nommé `description` d’une API n’est pas automatiquement une garantie
  de texte intégral ;
- les pages détaillées peuvent être protégées, modifiées ou inaccessibles sans
  navigateur ;
- une réponse HTML peut contenir du JSON-LD tronqué ou un conteneur non reconnu.

Conclusion de l’audit : une description de recherche doit être considérée comme
un aperçu tant qu’une fiche détaillée fiable ou un texte manifestement complet ne
l’a pas confirmée.

## 5. Conservation des annonces incomplètes

### Problème initial

Le pipeline écartait une annonce lorsque son hydratation échouait avant qu’elle
ne puisse être réellement exploitée :

```text
recherche → normalisation → hydratation → contrôle complet
          → matching → sauvegarde
```

### Nouveau comportement

```text
annonce détectée
  → tentative d’hydratation
      ├── succès → matching normal → stockage
      └── échec  → stockage avec statut INCOMPLÈTE
                   sans matching complet
```

Une annonce incomplète conserve :

- son identifiant interne Rocky ;
- sa source et son identifiant externe ;
- ses URLs ;
- son résumé court ;
- les autres métadonnées disponibles ;
- `description_is_full = false` ;
- le statut utilisateur `INCOMPLÈTE`.

Elle n’est ni supprimée, ni ignorée silencieusement, ni rematchée automatiquement
à chaque veille.

### Fichiers principaux

- orchestration : `dashboard/rocky/watch.py` ;
- statuts : `dashboard/rocky/statuses.py` ;
- stockage : `dashboard/rocky/repository.py` ;
- hydratation : `dashboard/rocky/job_importer.py` ;
- file dédiée : `dashboard/page_enrichment.py`.

### Non-régression couverte

- une annonce complète suit toujours le pipeline normal ;
- une hydratation en échec conserve l’annonce ;
- l’annonce reçoit `INCOMPLÈTE` ;
- elle ne passe pas au matching complet ;
- un nouvel échec de réenrichissement ne la supprime pas.

## 6. Réenrichissement volontaire et fallback TheirStack

### Stratégie

Le réenrichissement est une action utilisateur. Pour une annonce incomplète :

1. Rocky retente le mécanisme de la source d’origine ;
2. si le détail reste indisponible, Rocky peut interroger TheirStack ;
3. le résultat TheirStack doit correspondre de manière suffisamment fiable ;
4. seule une description réellement plus complète et non tronquée est retenue ;
5. le matching est recalculé après succès.

### Rapprochement prudent

Le client TheirStack utilise `POST /v1/jobs/search` avec l’entreprise et le poste,
limités à trois candidats. Le score d’identité combine :

- similarité de l’intitulé ;
- similarité de l’entreprise ;
- corroboration par URL ;
- proximité de date ;
- localisation compatible.

La description doit être nettement plus longue que l’aperçu existant et ne pas
présenter de terminaison tronquée.

### Provenance

Une annonce Apec enrichie via TheirStack reste une annonce Apec. Les informations
distinctes sont :

```text
source de collecte              = Apec
source d’enrichissement         = TheirStack
identifiant externe de collecte = identifiant Apec
identifiant d’enrichissement    = identifiant TheirStack
```

### Sécurité

- `THEIRSTACK_API_KEY` est lue depuis `.env` ;
- `.env.example` contient seulement le nom de variable ;
- aucune erreur affichée ne reprend la valeur du secret ;
- une annonce déjà complète ne déclenche jamais TheirStack ;
- les crédits ne sont consommés que lors d’une action pertinente.

### Documentation

La stratégie est décrite dans `docs/theirstack_enrichment.md`.

## 7. Comparaison des dashboards A, B et C

### Version A — institutionnelle

Philosophie : liste rationnelle, filtres clairement identifiés, hiérarchie proche
d’un service public de l’emploi, détails derrière une zone secondaire.

### Version B — cockpit

Philosophie : métriques en tête, filtres compacts, cartes rapidement scannables,
score très visible et navigation orientée décision.

### Version C — simple et accessible

Philosophie : peu d’informations simultanées, grandes cartes, actions immédiates
et détails secondaires masqués.

### Comparateur

Un point d’entrée commun a temporairement permis de basculer entre A, B et C afin
de comparer réellement les trois versions dans Streamlit.

### Décision

La version cockpit a été retenue comme Rocky V2. Les versions A et C ont ensuite
été supprimées, sans remplacer l’ancien `dashboard/app.py`, qui reste la référence
fonctionnelle V1.1 pour les composants repris.

## 8. Cockpit Rocky V2

### Navigation

La navigation unique contient :

- Cockpit ;
- ATS V3 ;
- À enrichir ;
- Fiche annonce ;
- Ajouter une URL ;
- Mes profils ;
- Monitoring.

Les outils V1.1 ont été réutilisés au lieu d’être reconstruits.

### Métriques interactives

Les métriques du cockpit agissent comme des filtres :

- Flux connu ;
- Nouvelles sur une période ;
- Exploitables ;
- À enrichir ;
- Meilleur score.

Un clic sur une métrique affiche les cartes correspondantes. « À enrichir » ouvre
la page dédiée.

La durée des nouvelles annonces est réglable sur :

- 1 jour ;
- 3 jours ;
- 7 jours ;
- 1 mois.

Le seuil de score est réglé avec un curseur de 0 à 100, par pas de 5, à la place
des boutons `+` et `-`.

### Filtres et tri

Le cockpit permet de filtrer ou trier notamment par :

- texte ;
- source ;
- statut ;
- lieu ;
- score ;
- date ;
- télétravail ;
- salaire lorsqu’il est disponible.

### Chatbot

Le chatbot V1.1 et ses paramètres LLM ont été conservés, puis présentés sous
forme de bouton flottant ouvrant une petite fenêtre de discussion. Aucun accès
LLM direct à PostgreSQL n’a été ajouté.

## 9. Visibilité des statuts

### Annonces écartées

Les annonces `ÉCARTÉE` restent en base pour de futurs usages ou entraînements,
mais sont retirées des affichages opérationnels du cockpit.

### File d’enrichissement

La page « À enrichir » ne contient que les annonces dont le statut est
`INCOMPLÈTE`. Une annonce ayant changé de statut sort immédiatement de cette page,
mais reste dans PostgreSQL.

### Statuts dans les cartes

Chaque carte du cockpit propose une modification directe du statut. La fiche
annonce possède également son sélecteur et son bouton d’enregistrement.

## 10. Fiche annonce complète

### Organisation

La carte du cockpit reste compacte. Le détail est déplacé vers une page dédiée
organisée en trois onglets :

1. annonce et modifications ;
2. matching détaillé ;
3. lettre et candidature.

### Données et actions disponibles

- poste, entreprise, lieu et source ;
- score Rocky ;
- description complète ou avertissement d’incomplétude ;
- statut ;
- contrat et temps de travail ;
- télétravail, salaire, niveau d’expérience et formation ;
- dates de publication et de clôture ;
- identifiants et provenance ;
- modification des champs métier issus de V1.1 ;
- recalcul du matching ;
- réenrichissement volontaire ;
- ouverture de l’annonce source ;
- bouton « Postuler » vers l’URL de candidature.

### Détail du matching

Le matching est présenté par catégories :

- compétences techniques ;
- compétences transversales ;
- compétences proches mais non reconnues, affichées « à vérifier ».

La distinction entre correspondance exacte et proximité évite de masquer les
écarts réels.

## 11. Lettre de motivation et dossier de candidature

### Atelier de lettre

La fiche annonce reprend la génération V1.1 :

- génération via le LLM configuré ;
- texte modifiable avant export ;
- prévisualisation ;
- création DOCX et PDF ;
- copie du CV associé au profil ;
- création d’un dossier de candidature.

### Éditeur de lettre

Après plusieurs essais de zone fixe/défilante, l’éditeur a été ajusté pour afficher
la totalité du texte sans barre de défilement interne. Sa hauteur est estimée à
partir du nombre de lignes visuelles afin de rester comparable à l’aperçu.

### Candidature

Le bouton principal ouvre l’URL de candidature si elle existe, avec l’URL source
accessible séparément. Rocky prépare les documents mais ne soumet jamais une
candidature automatiquement.

## 12. ATS V1 et ATS V2

### ATS V1

Le premier rapport vérifie notamment :

- extractibilité du PDF ;
- nombre de pages et volume de texte ;
- couverture des compétences de l’annonce ;
- présence de coordonnées ;
- cohérence de la lettre avec le poste et l’entreprise ;
- indicateurs CV, lettre et score synthétique.

### Limite constatée

Le premier moteur pouvait manquer des termes réellement présents lorsque le PDF
séparait les caractères ou lorsque les formulations différaient légèrement. Un
score apparemment fragile pouvait donc venir de la lecture PDF plutôt que du CV.

### ATS V2

La V2 a ajouté :

- réparation des espacements anormaux issus de l’extraction PDF ;
- reconnaissance exacte par frontières de mots ;
- séparation entre compétences exactes, proches et absentes ;
- diagnostic plus prudent ;
- conservation des termes réellement manquants ;
- recommandations reliées à des observations mesurables.

### Éditeur texte du CV pour ATS

Une version texte du CV peut être modifiée pour corriger ce que voit l’analyseur.
Cette modification est enregistrée séparément et ne remplace pas le PDF original.
Un bouton permet de restaurer le texte extrait du CV.

### Format conseillé

Le PDF reste le fichier réel à tester. Un DOCX peut être fourni en complément
pour comparer l’extraction, mais ne doit pas remplacer artificiellement le fichier
qui sera réellement envoyé au recruteur.

## 13. Banc de robustesse ATS V3

### Principe

ATS V3 est indépendant de V1 et V2. Il ne cherche pas à maximiser le score du CV
de Nicolas mais à mesurer sa robustesse face à plusieurs méthodes de lecture.

```text
fichier CV réel
  → plusieurs parseurs indépendants
  → extractions structurées communes
  → comparaison des divergences
  → matching lexical avec l’annonce
  → équivalences sémantiques séparées
  → diagnostic actionnable
```

### Parseurs retenus

Pour le PDF :

| Parseur | Rôle | Licence |
| --- | --- | --- |
| pypdf | extraction brute et métadonnées | BSD-3-Clause |
| pdfminer.six | extraction orientée mise en page | MIT |
| pypdfium2/PDFium | extraction indépendante et rendu visuel | Apache-2.0/BSD-3-Clause |

Pour le DOCX :

- `python-docx` ;
- lecture OOXML indépendante par ZIP/XML.

### Étude d’ATS Screener

Le projet `sunnypatell/ats-screener`, sous licence MIT, a servi de benchmark
conceptuel. Aucune application ou composant TypeScript n’a été recopié. Les idées
retenues sont la comparaison des stratégies, la séparation parsing/matching et
l’affichage de simulations explicitement approximatives.

### Indicateurs séparés

- robustesse du parsing ;
- cohérence inter-parseurs ;
- couverture exacte ;
- couverture lexicale ;
- couverture des compétences obligatoires ;
- mots-clés ;
- équivalences sémantiques séparées ;
- risques de structure ;
- résumé secondaire transparent.

Formule du résumé secondaire :

```text
45 % robustesse + 40 % couverture lexicale + 15 % mots-clés
```

### Benchmarks approximatifs

- Workday-like ;
- Taleo/Oracle-like ;
- iCIMS-like ;
- Greenhouse-like ;
- Lever-like ;
- SuccessFactors-like.

Ces résultats ne prétendent jamais reproduire les algorithmes propriétaires.

### Vue « ce que voit l’ATS »

L’utilisateur peut comparer le rendu visuel du CV au texte brut ou structuré de
chaque parseur. Une défaillance d’un moteur reste visible au lieu d’être masquée.

### Tests de non-biais

- suppression volontaire d’une compétence ;
- PDF multi-colonnes ;
- CV externe fictif ;
- comparaison PDF/DOCX ;
- annonce éloignée du profil ;
- séparation stricte entre lexique et sémantique ;
- absence d’injection silencieuse des compétences du profil Rocky.

### Documentation

La méthode complète est dans `docs/ats_v3_methodology.md`.

## 14. Compétences des profils

### Lecture automatique du CV

Un bouton placé entre le CV associé et la saisie manuelle permet de :

1. lire le PDF avec l’extracteur déjà présent ;
2. reconnaître les compétences de la taxonomie Rocky ;
3. estimer un niveau simple à partir du contexte et des occurrences ;
4. ajouter uniquement les compétences absentes.

Les saisies manuelles existantes ne sont jamais écrasées.

### Gestion manuelle conservée

La saisie manuelle permet toujours de définir :

- nom ;
- catégorie ;
- niveau ;
- années d’expérience ;
- caractère principal ou secondaire.

### Modification des compétences

Chaque compétence enregistrée affiche désormais ses années d’expérience et un
bouton « Modifier ». Le formulaire permet d’éditer le nom, la catégorie, le niveau,
les années et le statut de compétence principale. La suppression reste disponible.

Aucune migration n’a été nécessaire pour cette évolution : `years_experience`
existait déjà dans `candidate_skills`.

## 15. Gestion multi-profils

### Diagnostic initial

Rocky possédait déjà :

- `candidate_profiles` ;
- un profil actif ;
- `job_offers` centralisée ;
- `job_matches(job_id, profile_id)`.

La récupération des annonces utilisait le profil pour le score, mais la relation
entre une annonce incomplète et un profil n’était pas suffisamment générale : une
annonce sans matching devait aussi pouvoir appartenir au flux d’un profil.

### Solution retenue

Une table de liaison minimale `profile_jobs` a été ajoutée lors de ce chantier :

```text
candidate_profiles
        │
        ├── profile_jobs ── job_offers
        │
        └── job_matches ─── job_offers
```

- `job_offers` reste centrale ;
- `profile_jobs` exprime l’appartenance au flux ;
- `job_matches` conserve le score propre au profil ;
- `(profile_id, job_id)` empêche les doublons de relation.

### Chemin jusqu’au cockpit

```text
candidate_profiles.is_active
  → fetch_active_profile()
  → get_jobs_for_profile(profile.id)
  → dashboard_common.load_data()
  → dashboard_b.py
```

Le cockpit ne reçoit donc que les annonces du profil actif sans être dupliqué.

### Veille multi-profils

- nouvelle et complète : insertion, rattachement, matching ;
- nouvelle et incomplète : insertion et rattachement sans matching ;
- déjà connue : pas de duplication, ajout du rattachement ;
- connue et complète mais jamais matchée pour ce profil : calcul d’un score propre
  au nouveau profil.

### Reprise historique

Les schémas PostgreSQL et SQLite effectuent une reprise idempotente depuis :

1. `job_matches` ;
2. `applications` ;
3. les intervalles de `watch_runs` ;
4. le profil historique le plus ancien pour les annonces restantes sans trace.

### Limite volontaire

Le statut utilisateur reste porté par `job_offers`. Une annonce partagée a donc
actuellement le même statut pour tous les profils.

### Documentation

Le détail et le retour en arrière sont décrits dans `docs/multi_profile_jobs.md`.

## 16. Actions groupées dans « À enrichir »

### Tout enrichir

Un bouton « Tout enrichir » retente l’ensemble de la file du profil actif. Un seul
client TheirStack est réutilisé pendant le lot. Une barre de progression et un
résumé indiquent :

- tentatives ;
- enrichissements réussis ;
- annonces restant incomplètes ;
- erreurs isolées.

Un échec n’interrompt pas les annonces suivantes.

### Multi-sélection

Le tableau Streamlit permet de sélectionner plusieurs annonces et d’appliquer un
statut commun. La mise à jour est exécutée dans le repository par une fonction
groupée simple.

### Correctif IndexError

Une sélection Streamlit pouvait conserver des positions devenues invalides après
un filtre, un tri ou un rerun :

```text
IndexError: single positional indexer is out-of-bounds
```

Le correctif transforme les positions en IDs uniquement lorsqu’elles restent dans
les limites du DataFrame courant. La clé du tableau inclut également une signature
de la liste affichée, ce qui évite de réutiliser une sélection périmée.

### Tri et lieu

La file affiche le lieu et propose des tris simples :

- dernière mise à jour ;
- publication récente ou ancienne ;
- intitulé ;
- entreprise ;
- lieu ;
- source.

## 17. Monitoring des sources

### Objectif

Rendre visible quelles sources ont fonctionné et lesquelles sont restées en erreur
pendant une veille.

### Résultat

Le monitoring présente, pour chaque veille récente :

- sources réussies ;
- sources en erreur ;
- nombre d’annonces détectées ;
- message d’erreur lisible et nettoyé ;
- profil utilisé ;
- état global `SUCCESS`, `PARTIAL` ou `FAILED`.

Les erreurs d’une plateforme n’arrêtent pas les suivantes. Les messages techniques
sensibles et les credentials ne sont jamais affichés.

### Limite historique

Les veilles antérieures à l’ajout du détail par source ne peuvent afficher que les
erreurs qui étaient déjà enregistrées à cette date.

## 18. Collecte Indeed via TheirStack

### État antérieur

Indeed était collecté depuis sa page publique. Les vérifications navigateur et les
protections Cloudflare rendaient ce connecteur instable. TheirStack existait déjà,
mais uniquement comme fallback d’enrichissement.

### Nouveau rôle distinct

```text
TheirStack
├── collecte Indeed
└── enrichissement volontaire d’une annonce existante
```

Le client HTTP est partagé, mais les comportements métier restent séparés.

### Requête de collecte

Le connecteur utilise :

```text
POST https://api.theirstack.com/v1/jobs/search
```

Paramètres principaux :

- `job_title_or` depuis les métiers ciblés ;
- `job_country_code_or=["FR"]` ;
- `url_domain_or=["indeed.com"]` ;
- `job_location_or` après résolution par le catalogue TheirStack ;
- `employment_statuses_or` lorsque les contrats sont convertibles ;
- `workplace_types_or` pour les préférences remote/hybride ;
- `posted_at_max_age_days` ;
- `is_closed=false` ;
- `limit=WATCH_RESULTS_PER_QUERY` ;
- `offset=0`.

Le catalogue des lieux est interrogé via :

```text
GET https://api.theirstack.com/v0/catalog/locations
```

### Normalisation

Les champs TheirStack sont transformés en `JobOffer` Rocky :

- identifiant Indeed `jk` lorsqu’il existe ;
- URL source Indeed ;
- URL finale de candidature ;
- poste, entreprise et localisation ;
- description ;
- date ;
- télétravail/hybride ;
- statut d’emploi ;
- séniorité ;
- salaire ;
- technologies détectées.

### Provenance

```text
source_name    = Indeed
collector_name = TheirStack
```

Le champ d’enrichissement reste indépendant.

### Déduplication

Le rapprochement existant utilise :

- `source_name + external_id` ;
- URL source ;
- URL de candidature ;
- correspondance croisée entre URL source et URL de candidature.

Une offre Indeed pointant vers une fiche carrière déjà connue peut ainsi être
rattachée à un autre profil sans dupliquer la ligne centrale.

### Gestion des erreurs

- absence de configuration ;
- timeout ;
- réponse invalide ;
- HTTP 402/quota ;
- HTTP 429/limite de débit ;
- autre erreur HTTP.

Chaque panne reste isolée et les autres sources poursuivent la veille.

### Tests et appel réel

- Indeed seul ;
- Indeed avec une autre source ;
- normalisation ;
- provenance ;
- stockage ;
- multi-profils ;
- déduplication inter-sources ;
- panne TheirStack ;
- non-régression du fallback d’enrichissement.

Un appel réel a été effectué avec une limite d’un résultat, soit au maximum un
crédit TheirStack. Il a réussi.

### Limites

- TheirStack facture les résultats retournés, y compris si Rocky les reconnaît
  ensuite comme doublons ;
- la correspondance entre statuts d’emploi internationaux et CDI/CDD reste
  imparfaite ;
- une seule page est volontairement demandée pour maîtriser les crédits ;
- TheirStack applique aussi sa propre déduplication et sa couverture n’est pas un
  recensement exhaustif du marché.

## 19. Diagnostic des 20 annonces Indeed non insérées

### Demande

Comprendre le bilan :

```text
20 annonces Indeed reçues
0 nouvelle
0 doublon
```

Ce chantier a été traité uniquement en lecture et en diagnostic. Aucun code, schéma
ou modèle de données n’a été modifié.

### Veille analysée

Veille n°13, profil `Data Analyst / Data Scientist` :

| Source | Reçues | Ajoutées | Doublons | Rejets déduits |
| --- | ---: | ---: | ---: | ---: |
| Adzuna | 31 | 0 | 22 | 9 |
| LinkedIn | 36 | 0 | 6 | 30 |
| Indeed/TheirStack | 20 | 0 | 0 | 20 |
| Welcome to the Jungle | 40 | 0 | 11 | 29 |
| Apec | 66 | 1 | 65 | 0 |
| Wellfound | 40 | 0 | 8 | 32 |
| Total | 233 | 1 | 112 | 120 |

Équation vérifiée :

```text
233 reçues = 1 ajoutée + 112 doublons + 120 rejetées
```

### Chemin exact des annonces Indeed

```text
20 résultats normalisés
  → 0 doublon
  → descriptions considérées complètes
  → matching calculé
  → 20 scores inférieurs à 70
  → 20 rejets avant insertion
```

La branche responsable est dans `WatchService.run()` :

```python
if result.score < self.settings.match_threshold:
    summary["below_threshold_count"] += 1
    summary["rejected_count"] += 1
    continue
```

### Pourquoi elles semblaient disparaître

Le résumé par connecteur affichait les reçues, nouvelles, doublons et actualisations,
mais pas les rejets par source. Les 20 rejets Indeed étaient donc visibles uniquement
dans le total global de 120 rejets.

### Limite du diagnostic rétrospectif

Les scores individuels n’étaient pas enregistrés car le rejet intervient avant
`insert_job()` et `save_match()`. On sait avec certitude qu’ils étaient inférieurs
à 70, mais leurs valeurs exactes ne sont plus disponibles sans relancer une collecte
payante ou instrumenter temporairement une prochaine exécution.

### Instrumentation envisagée mais non réalisée

Une instrumentation locale pourrait calculer en mémoire :

- reçues ;
- doublons ;
- incomplètes conservées ;
- scores sous le seuil ;
- insérées ;
- actualisées ;
- score minimal, moyen et maximal des rejets ;
- rejets par raison.

Conformément à la contrainte d’observabilité, ces données devraient rester dans un
dictionnaire Python temporaire, les logs et le résumé Streamlit immédiat. Elles ne
doivent pas créer de table, de colonne ou de migration et ne doivent pas être
enregistrées dans PostgreSQL.

## 20. Tests et contrôles consolidés

La suite actuelle couvre notamment :

| Domaine | Vérifications principales |
| --- | --- |
| Sources | mappings, erreurs nettoyées, registre, Indeed/TheirStack |
| Veille | seuil, isolation des pannes, annonces incomplètes, doublons |
| Enrichissement | succès, échec, lot, provenance, secret |
| Multi-profils | filtrage cockpit, relation partagée, reprise historique |
| Dashboard | démarrage, métriques, statuts, file incomplète, sélection périmée |
| Matching | explication, critères absents, descriptions courtes exclues |
| ATS V1/V2 | PDF, extraction, compétences exactes/proches, éditeur texte |
| ATS V3 | parseurs, non-biais, PDF/DOCX, benchmarks, sémantique séparée |
| Lettres | variables, édition, DOCX/PDF |
| Profils | lecture CV, compétences, préservation des saisies manuelles |
| Repository | PostgreSQL/SQLite, provenance, mises à jour, source_results |

Commandes usuelles :

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke_dashboard.py
.venv/bin/python scripts/check_connections.py
```

## 21. État actuel et principes pour la suite

### Ce qui est stabilisé

- cockpit V2 unique ;
- profils multiples ;
- annonces centrales ;
- descriptions incomplètes conservées ;
- réenrichissement volontaire ;
- TheirStack pour enrichissement et collecte Indeed ;
- provenance distincte ;
- ATS V1, V2 et V3 comparables ;
- actions groupées ;
- monitoring des connecteurs ;
- serveur local opérationnel.

### Principes à conserver

- privilégier les fonctions existantes ;
- ne pas disperser le profil actif dans toute l’interface ;
- ne pas dupliquer les annonces ou le cockpit ;
- ne pas utiliser le LLM pour masquer une donnée absente ;
- conserver les sources, URLs et identifiants ;
- isoler les pannes externes ;
- ne jamais journaliser de secret ;
- distinguer les diagnostics temporaires des données métier persistantes ;
- ne pas modifier l’architecture pour un simple besoin d’observabilité.

## 22. Test fonctionnel de Rocky V2 — 13 août 2026

### Objectif et périmètre

Un contrôle fonctionnel complet a été réalisé après la suppression de l’ancien
point d’entrée `dashboard/app.py`. Le test a porté sur le serveur local, les tests
automatisés, les pages Streamlit, les interactions sans écriture et les journaux
d’exécution.

Le navigateur contrôlable n’étant pas disponible pendant cette session, les
interactions ont été exécutées avec le moteur de test officiel de Streamlit. Ce
contrôle exécute réellement les pages, les reruns et les widgets, mais ne permet
pas d’évaluer précisément le rendu visuel ou responsive dans un navigateur.

Les actions susceptibles de modifier PostgreSQL, de consommer des crédits ou
d’appeler le LLM n’ont pas été déclenchées : veille complète, réenrichissement,
changement de statut, sauvegardes et conversation avec Rocky.

### Résultat général

Rocky V2 est fonctionnel et aucun crash bloquant n’a été reproduit :

- serveur sain sur `http://127.0.0.1:8501` ;
- processus Streamlit lancé avec `dashboard/dashboard_v2.py` ;
- 74 tests automatisés réussis ;
- toutes les pages chargées sans exception avec PostgreSQL réel ;
- ancien `IndexError` de la multisélection non reproduit ;
- serveur toujours opérationnel après les contrôles.

### Parcours validés

- métriques interactives du cockpit ;
- périodes 1, 3, 7 et 30 jours ;
- recherche, seuil de score, source, lieu, télétravail et vues rapides ;
- passage de la métrique « À enrichir » vers la page dédiée ;
- affichage, recherche, filtres et tris des neuf annonces incomplètes ;
- navigation d’une carte vers sa fiche annonce complète ;
- présence des onglets « Annonce et modifications », « Matching détaillé » et
  « Lettre et candidature » ;
- présence de l’éditeur de lettre et du texte ATS du CV ;
- exécution sans exception des analyses ATS V1, V2 et V3 ;
- chargement des trois profils et de leurs compétences ;
- affichage des réussites et erreurs par connecteur dans le monitoring.

### Dysfonctionnement 1 — périodes récentes décalées d’un jour

Priorité : moyenne.

Le calcul « N jours » utilise une borne égale à `date.today() - N jours` et
l’inclut dans le résultat. Il couvre donc N+1 dates calendaires : aujourd’hui et
les N jours précédents.

Constat effectué avec les données du profil actif :

| Période | Résultat actuel | Résultat sur N dates calendaires |
| --- | ---: | ---: |
| 1 jour | 30 | 11 |
| 3 jours | 43 | 42 |
| 7 jours | 59 | 54 |
| 1 mois | 105 | 105 |

L’absence de différence sur un mois est une coïncidence liée aux dates présentes
dans la base. La même borne est employée dans le calcul de la métrique et dans le
filtrage des cartes, ce qui rend les deux affichages cohérents entre eux mais
décalés par rapport au libellé demandé.

Fichiers concernés :

- `dashboard/dashboard_common.py`, fonction `metric_counts()` ;
- `dashboard/dashboard_b.py`, filtre de la métrique `recent`.

### Dysfonctionnement 2 — rejets absents du détail par source

Priorité : moyenne.

Le monitoring peut afficher :

```text
Indeed via TheirStack · 20 détectées · 0 nouvelle · 0 doublon
```

Il n’indique pas que les vingt annonces ont été rejetées parce que leur score était
inférieur au seuil automatique. Le compteur de rejet existe au niveau global de la
veille, mais les compteurs temporaires par source ne contiennent actuellement que :

- reçues ;
- insérées ;
- doublons ;
- actualisées.

Le parcours reste donc incomplet dans le monitoring :

```text
20 reçues → 20 sous le seuil → 0 insérée
```

est présenté comme :

```text
20 reçues → 0 nouvelle → 0 doublon
```

Fichiers concernés :

- `dashboard/rocky/watch.py`, construction de `source_result` ;
- `dashboard/page_monitoring.py`, affichage du résultat des connecteurs.

Cette lacune relève de l’observabilité d’exécution. Sa correction ne nécessite ni
table, ni colonne, ni migration : des compteurs Python temporaires par source sont
suffisants.

### Point de vigilance 3 — poids de rendu du cockpit

Priorité : basse à ce stade.

Le cockpit construit toutes les cartes immédiatement. Avec les 125 annonces du
profil actif, un rendu crée :

- 125 cartes et expanders ;
- 257 boutons ;
- 126 sélecteurs ;
- 398 métriques Streamlit ;
- 34 avertissements de description incomplète.

Le rendu automatisé a pris environ 1,31 seconde sur le Mac local. Ce n’est pas un
blocage actuel, mais l’absence de pagination ou de chargement progressif peut
devenir sensible lorsque le volume d’annonces augmentera.

### Anomalie externe — France Travail

Les veilles récentes restent au statut `PARTIAL` parce que les identifiants
applicatifs France Travail sont refusés. Il s’agit d’un problème de configuration
ou d’autorisation externe, pas d’un crash du pipeline Rocky.

Les autres sources récentes terminent correctement, notamment Indeed via
TheirStack. Les anciens avertissements Indeed liés à une vérification navigateur
appartiennent aux collectes antérieures à cette intégration.

### ATS observés pendant le contrôle

Sur l’annonce complète Rocky #36 :

- ATS V1 s’exécute mais conserve son comportement historique fragile, avec une
  couverture CV à 0 % et un score indicatif de 55/100 ;
- ATS V2 reconnaît correctement le texte normalisé, avec 100 % de mots-clés exacts
  et un score de 94/100 ;
- ATS V3 s’exécute avec trois parseurs et signale volontairement la fragilité du
  PDF : robustesse de parsing 52 %, cohérence 37 %, couverture lexicale 100 %.

Ces écarts sont cohérents avec la philosophie distincte des trois simulateurs et
ne constituent pas un dysfonctionnement de V3.

### Modifications réalisées

Aucune modification de code, de configuration ou de donnée n’a été effectuée
pendant ce diagnostic. Seul le présent compte rendu consolidé a été complété.

## 23. Évolutions d’interface et consolidation ATS — 22 août 2026

### Cockpit, file d’enrichissement et fiche annonce

- la carte du cockpit expose désormais directement le bouton « Ouvrir la fiche
  complète » ; il n’est plus caché dans l’analyse du matching ;
- le tri « Plus récentes » convertit explicitement les dates avant classement,
  ce qui évite l’erreur Pandas sur des colonnes catégorielles non ordonnées ;
- chaque annonce de la file « À enrichir » peut être modifiée manuellement depuis
  son expander. Le formulaire partagé marque la description comme complète,
  ajuste le statut si nécessaire et recalcule le matching ;
- dans la fiche annonce, le lien source redondant a été retiré, l’enregistrement
  du statut se trouve sous son sélecteur et les accès compacts « Provenance » et
  « Modifier l’annonce » ont été regroupés avant les métadonnées ;
- l’onglet de lettre présente maintenant l’éditeur pleine largeur, suivi de son
  aperçu pleine largeur dans une zone défilable. L’adresse de l’entreprise est
  saisie sur une ligne ; les liens superflus après « Postuler » ont été retirés.

### Navigation et profils

La navigation latérale est organisée en deux sections :

| Section | Pages visibles |
| --- | --- |
| Rocky | Cockpit, Mes profils, ATS, Ajouter une URL |
| Outils | Tout le flux, Monitoring |

Les pages internes « À enrichir » et « Fiche annonce » restent masquées de la
barre latérale et sont ouvertes depuis les actions contextuelles.

La page « Mes profils » conserve désormais le résultat du chargement du CV après
le rerun : le nom du fichier est confirmé en cas de succès et toute erreur PDF ou
d’écriture est affichée.

### ATS centralisé

La page anciennement nommée « ATS V3 » s’appelle désormais simplement « ATS ».
Elle centralise les trois analyses :

- le lancement V3 se situe directement sous le choix du CV et de l’annonce ;
- V1 et V2 utilisent le CV PDF réellement associé au profil, la lettre de
  motivation et l’annonce sélectionnée ;
- le sélecteur d’annonce se limite aux éléments de « Mes annonces » : annonces
  complètes, scorées et dans un statut de suivi ;
- la lettre existante est récupérée en priorité depuis le brouillon courant, puis
  depuis le dernier DOCX enregistré. En son absence, le bouton « Générer la lettre
  de motivation » ouvre la fiche concernée directement sur l’onglet Lettre ;
- ATS V2 n’offre plus de correction manuelle du texte extrait : les analyses V1
  et V2 mesurent le PDF réel pour exposer tout défaut de parsing à corriger dans le
  CV lui-même ;
- les rapports V1, V2 et V3 sont repliés dans des expanders pour préserver la
  lisibilité de la page.

### Vérification, Git et configuration locale

La suite complète a été exécutée après mise à jour des tests d’interface pour le
cockpit actuel et la centralisation ATS : **75 tests réussis**. Seuls des
avertissements Pandas non bloquants subsistent sur un calcul de durée.

La branche `nico-dev`, créée depuis `main`, contient les commits de mise à jour
des tests et de nettoyage du runtime Streamlit. Le fichier
`logs/rocky_streamlit.pid` est maintenant ignoré par Git : il ne doit jamais être
publié car il dépend de la machine locale.

Lorsqu’un clone local est placé dans un nouveau dossier, il faut y fournir un
fichier `.env` non versionné contenant la configuration PostgreSQL (ou
`DATABASE_URL`). Sans ce fichier, le serveur Streamlit démarre mais l’application
ne peut pas se connecter à la base. Cette configuration reste locale et ne doit
pas être ajoutée au dépôt.

## 24. Nettoyage du dépôt après déplacement — 26 août 2026

### Objectif

Rattacher le dossier local déplacé `Rocky_assistant_job` à la branche GitHub
`nico-dev` et empêcher la publication d'artefacts locaux ou de documents
personnels introduits pendant la réorganisation.

### Fichiers modifiés

- `.gitignore` ;
- `docs/comptes_rendus_consolides.md` ;
- `Template_lm_datascientist.pages` et
  `data/profiles/1/cv_ats.txt`, retirés de l'index Git mais conservés sur le
  disque local.

### Changements et décisions

- la branche locale suit désormais `origin/nico-dev`, qui contenait déjà les
  trois commits légitimes de tests, de nettoyage du PID Streamlit et de
  documentation ;
- l'ancien état local reste récupérable dans la branche
  `backup/nico-before-cleanup-20260826` ;
- les caches Python, environnements virtuels, journaux, PID, sorties de
  candidatures, anciens exports, CV et fichiers temporaires sont ignorés ;
- le fichier `.env` local et les documents privés restent présents sur la
  machine, sans être suivis par Git ;
- aucune modification fonctionnelle du code applicatif n'a été nécessaire.

### Vérifications et limites

- suite complète : **75 tests réussis**, avec 10 avertissements de dépréciation
  Pandas/NumPy déjà connus ;
- Streamlit démarré sur `127.0.0.1:8501` et endpoint de santé validé avec la
  réponse `ok` ;
- les appels réels aux services tiers ne font pas partie de cette vérification
  locale ; leurs identifiants et quotas restent dépendants de la configuration
  privée du fichier `.env`.

## 25. Index des documents associés

- `README.md` — installation, exploitation et architecture courante ;
- `docs/theirstack_enrichment.md` — rapprochement d’enrichissement ;
- `docs/multi_profile_jobs.md` — rattachement profil-annonce ;
- `docs/ats_v3_methodology.md` — méthode ATS V3 ;
- `database/schema.sql` — schéma PostgreSQL idempotent ;
- `database/schema_sqlite.sql` — schéma SQLite du déploiement Hugging Face ;
- `tests/` — spécifications exécutables des comportements décrits.
