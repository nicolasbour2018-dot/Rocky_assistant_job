# Plan de refonte Rocky — v2

> **Statut : VALIDÉ** — 24 septembre 2026, avec Nicolas.
> Remplace `docs/rocky-refonte-plan.md` (v1 provisoire). S'appuie sur `docs/rocky-architecture-audit.md` (Codex)
> et sur le parcours visuel du 24/09. Aucune modification applicative n'a encore été faite.

## 0. Comment utiliser ce document (agents)

- **Lire le plan en entier** avant de travailler sur une étape : il donne la vue d'ensemble, mais on ne réalise **qu'une étape à la fois**.
- Une étape est terminée quand **son critère de sortie est vérifié**, puis la vérification globale reste verte (lint, types, tests).
- Ne pas anticiper une étape suivante. Un constat hors périmètre est noté en section 8, pas corrigé au passage.
- **Ne jamais modifier l'ancien Rocky** (Streamlit) : il reste l'outil de Nicolas jusqu'à la bascule (F2).
- Mettre à jour la colonne « État » de l'étape (⬜ à faire · 🔄 en cours · ✅ terminée).
- Invariants conservés : Rocky ne postule jamais à la place de l'utilisateur ; Gmail en lecture seule ;
  aucun contournement des protections des sites ; matching déterministe et explicable.

## 1. Pourquoi une refonte

L'application actuelle est fonctionnelle mais **pas pertinente** : le scoring classe mal les annonces, la veille
et le tri Gmail produisent du bruit sans preuve, et l'interface est chargée. Les audits ont aussi relevé des défauts
d'intégrité (PDF réécrits, transactions coupées, veilles restées `RUNNING`, offres sous le seuil jetées sans trace)
et une dette de structure (`repository.py` > 2 500 lignes, dépendances inversées, tests en échec).
Objectif : repartir sur une base **propre**, organisée par métier, qui aide réellement à trouver du travail.

Diagnostic du scoring actuel (cause principale du manque de pertinence) : moyenne pondérée (compétences 55, intitulé 20,
contrat 8, lieu 8, télétravail 5, salaire 4) renormalisée sur les seuls critères présents ; la composante compétences
est calculée sur les compétences **détectées dans l'annonce**. Une annonce pauvre (1 compétence détectée, possédée)
obtient la composante pleine, une annonce riche est pénalisée ; l'intitulé est comparé au seul profil enregistré.
Le score récompense donc les annonces dont on sait le moins.

## 2. Décisions

| # | Décision |
|---|---|
| D1 | Rocky reste **multi-utilisateur** : comptes, sessions et SMTP conservés, rangés dans `system`. |
| D2 | **Un compte = un profil.** Plus de profil actif, de sélecteur ni de profils multiples. |
| D3 | Recherche multimétier par **pistes** dans le profil unique. Toutes les pistes alimentent la veille ; chaque offre garde la ou les pistes qui l'ont trouvée ; aucun choix ne masque d'offres. |
| D4 | **Archiver puis repartir d'une base neuve.** Dump complet et exports pour analyse ultérieure ; aucune migration de données. Les candidatures en cours ne sont pas réimportées. Seul le profil de Nicolas est réimporté (B5). *(Remplace l'ancienne D5 ; l'ancienne D4 — profils de test — devient sans objet.)* |
| D5 | **PostgreSQL seul.** Fin du schéma SQLite, y compris pour les tests (PostgreSQL de test). |
| D6 | **UI FastAPI + Jinja + HTMX**, validée par un prototype en B4. Plan B : NiceGUI. |
| D7 | Parcours complet conservé, réorganisé par étapes métier. |
| D8 | **France Travail** : connecteur conservé, désactivable, affiché « en attente d'accès ». La refonte n'en dépend pas. |
| D9 | **Migrations Alembic**, mises en place par l'agent dès le socle (apprentissage manuel reporté). |
| D10 | **Nouveau Rocky développé à côté de l'ancien**, sur une branche ; l'ancien reste utilisé tel quel (sans correctif) jusqu'à la bascule. Pas de cohabitation des deux interfaces. La propreté prime sur la date de bascule. |
| D11 | **Sessions persistantes** : cookie `HttpOnly`, `Secure` en HTTPS, `SameSite=Lax`, renouvellement glissant ; l'utilisateur reste connecté jusqu'à déconnexion ou expiration. |
| D12 | **Planification** : un seul déclencheur, le planificateur intégré. Au démarrage, si la dernière veille date de plus de 24 h, 🏠 Aujourd'hui affiche le retard et propose un rattrapage. Cron seulement en cas de déploiement serveur. |
| D13 | **Architecture par modules métier** (hexagonale progressive) : `profil`, `offres`, `candidatures`, `messages`, sur un socle technique `system`. Pas de découpage par couches techniques globales. |
| D14 | **Le scoring produit des données d'entraînement** pour un futur modèle de ML (réalisé plus tard, à la main, par Nicolas) : caractéristiques et preuves par composante, version des règles, décisions utilisateur avec raison (= étiquettes). |
| D15 | **Hébergement** : développement local (Docker) pendant la refonte ; VPS après la bascule, d'abord pour Nicolas, puis quelques alpha-testeurs. |
| D16 | **Étapes courtes avec critères de sortie**, sans estimation de durée. |

## 3. Architecture cible

### Arborescence

```
rocky/
  system/        base, config, comptes & sessions, événements, LLM, fichiers, planificateur, layout web
  profil/        profil unique FR/EN, pistes, compétences (alias canoniques), CV maître
  offres/        sources, import URL, analyse d'annonce, scoring, veille, décisions
  candidatures/  dossier, statuts, documents (CV, lettre), révisions, envoi, suivi
  messages/      Gmail, classification, alertes emploi, décisions sur les candidatures
tests/
docs/
```

À la racine, uniquement l'inévitable : `pyproject.toml`, `docker-compose.yml`, `.env.example`, `README`.

Chaque module métier suit la même forme interne : règles métier (fonctions pures, dataclasses) → cas d'usage →
accès SQL du module → routes FastAPI et gabarits HTMX. Les modules utilisent `system`, ils ne le recopient pas.
Les cas d'usage sont testables avec de faux adaptateurs (sans FastAPI, SQL ni Gmail). Pas d'interface par table
ni de hiérarchie de classes sans besoin réel.

### Adaptateurs

Sources d'offres (contrat `JobSource` conservé) · Gmail lecture seule · SQL par module · fichiers PDF · navigateur
(préremplissage) · LLM (Gemini, délais d'attente, sorties structurées validées).

### Modèle de données (esquisse, précisée dans chaque étape)

- `accounts` 1—1 `profile` (+ localisations FR/EN) 1—n `search_tracks` (pistes).
- `job_offers` : faits de l'annonce uniquement ; lien n—n vers les pistes qui l'ont trouvée.
- `match_scores` : score, confiance, détail et preuves par composante, caractéristiques, **version des règles**.
- `job_decisions` : valeur (à examiner, intéressé, écarté, plus tard), raison, auteur (`user`, `rule`, `ai`), date.
- Indicateurs calculés (incomplète, ancienne, sous le seuil) plutôt que statuts stockés.
- `applications` : étapes, prochaine action datée, révisions immuables de documents (chemin + hash).
- `email_messages` : classification, règle déclenchée, extrait justificatif, confiance, auteur, corrections.
- `events` : journal en ajout seul de toutes les décisions et transitions.

### Parcours cible (écrans)

```
🏠 Aujourd'hui      → ce qui demande ton attention maintenant
🔎 Offres           → Découvrir & décider
📝 Candidatures     → Préparer → Envoyer → Suivre
📬 Messages         → Retours recruteurs & alertes (avec preuves)
📈 Bilan            → Apprendre de sa recherche
👤 Profil & kit     → CV maître, pistes, compétences, FR/EN, « Vérifier mon CV »
⚙️ Système          → Sources, veilles, Gmail, planification, diagnostics
🐾 Rocky (tiroir)   → assistant contextuel, chargé à l'ouverture seulement
```

Règles de conception : une action principale par écran ; changement de statut en un geste ; confirmation uniquement
pour l'irréversible ; explications derrière un « Pourquoi ? » ; vocabulaire unique ; états vides explicatifs ;
aucun identifiant interne affiché.

## 4. Plan d'étapes

### A. Préparer

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| A1. Archive | `pg_dump` complet ; export Parquet + CSV des offres, scores, rattachements, candidatures, événements, mails et décisions Gmail ; copie des documents ; tag Git de l'ancienne version | Dump restauré sur base vierge avec comptes identiques ; exports lisibles dans un notebook | ✅ |
| A2. Cadrage écrit | Ce plan dans `docs/` ; `AGENTS.md` (écritures autorisées, arborescence, conventions) ; nouveau code sur une branche ; ancien Rocky lancé depuis un `git worktree` séparé ; règles `.claude/rules/` alignées | Un agent sait sans ambiguïté ce qu'il a le droit de toucher | ✅ |

### B. Socle `system` et `profil`

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| B1. Squelette | Arborescence ; Docker Compose (app, PostgreSQL, PostgreSQL de test) ; configuration `.env` ; ruff + vérificateur de types ; pytest sur PostgreSQL ; commande unique de vérification | Vérification verte en moins de 2 min | ✅ |
| B2. Base et événements | Connexion ; Alembic (première révision) ; journal d'événements en ajout seul | `upgrade` / `downgrade` fonctionnent sur base vide | ✅ |
| B3. Comptes et sessions | Comptes, SMTP ; sessions D11 ; tout le SQL d'authentification dans l'accès SQL de `system` | Rechargement, URL directe et redémarrage du navigateur gardent la session ; la déconnexion l'invalide | ✅ |
| B4. Coque web et prototype | FastAPI + Jinja + HTMX ; layout et 7 entrées de navigation ; prototype de l'écran de tri sur données factices | Décision explicite : HTMX confirmé ou plan B (NiceGUI) | ✅ |
| B5. Profil et pistes | Profil unique FR/EN ; compétences avec alias canoniques (ex. « NLP » = « Traitement du langage naturel (NLP) ») ; pistes (intitulés, mots-clés, lieux) ; réimport du profil de Nicolas depuis l'archive ; édition séparée de l'onboarding ; projets affichés proprement ; activation sans kit anglais | Profil réimporté sans doublons ; au moins 2 pistes définies | ✅ |

### C. Offres

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| C1. Sources | Contrat `JobSource` et registre repris ; connecteurs portés un à un ; APEC avec filtre de lieu et gestion honnête des descriptions incomplètes ; France Travail « en attente d'accès » (D8) ; noms de source normalisés | Chaque connecteur testé sur jeux de données enregistrés ; une panne de source est isolée et visible | ✅ |
| C2. Import par URL | JSON-LD puis HTML ; erreurs remontées avec leur raison (plus d'exception silencieuse) | Un lien invalide affiche sa raison | ✅ |
| C3. Analyse d'annonce | `job_analysis` rapatrié dans `offres` ; compétences via les alias ; critères éliminatoires distincts des préférences ; date limite ; TJM distinct du salaire annuel ; description mise en forme ; résumé de description | Extraction mesurée sur un échantillon de l'archive | ✅ |
| C4. Scoring : règles | Fonction pure sans effet de bord (ne modifie ni l'offre ni la base) ; **preuve minimale** (pas de composante compétences pleine sur 1–2 compétences) ; **indice de confiance** affiché ; intitulé comparé aux intitulés des pistes ; détail et preuves par composante ; version des règles ; caractéristiques stockées (D14) | Chaque score s'explique composante par composante ; la « Data Protection Analyst » (79,6 % en v1) ne remonte plus | ✅ |
| C5. Scoring : calibrage | Nicolas annote 40–50 annonces de l'archive (pertinente / non, avec motif) ; comparaison des classements ancien vs nouveau ; ajustement des règles | Les annonces jugées pertinentes remontent ; écart chiffré et documenté | ✅ |
| C6. Veille | Veille par pistes ; **toutes** les offres conservées, sous le seuil avec leur motif ; offre + rattachement aux pistes + score écrits comme une unité cohérente et idempotente ; veille toujours close (terminée / partielle / échouée / interrompue) ; source en attente ≠ échec ; planificateur unique et rattrapage (D12) | Une panne simulée laisse un statut final explicite et aucune offre orpheline ou sans score | ✅ |
| C7. Écran Offres | Décisions (valeur, raison, auteur) ; mode tri une offre à la fois au clavier ; liste compacte filtrable (piste, sous le seuil, incomplètes) ; fiche latérale avec synthèse de décision (date limite, éliminatoires, preuves du profil, manques) et « Pourquoi ? » ; retour « pertinente / non pertinente » avec motif (étiquettes D14) | Tri de 20 offres au clavier ; chaque décision est tracée dans `events` | ✅ |

### D. Candidatures

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| D1. Dossier et statuts | Étapes (préparée, préremplie, envoyée, suivie…) ; transitions et **annulation dans une seule transaction** ; prochaine action datée, différable | Une panne injectée pendant l'annulation ne laisse aucun état contradictoire | ✅ |
| D2. CV maître et rendu | CV structuré FR/EN ; gabarit HTML/CSS → PDF (Playwright) ; listes déterministes ; fin du verrou Canva (SHA-256, coordonnées pixels) et de LibreOffice ; « Vérifier mon CV » (ATS V3 porté) ; import d'un CV PDF et **gabarit par compte déduit du CV importé**, gabarit neutre à défaut (décision D2) | CV FR validé visuellement par Nicolas (EN aussi quand un CV anglais est importé : import facultatif, décision D2, Q33) ; parsing du PDF vérifié ; le gabarit déduit du CV Canva de Nicolas le reproduit à l'identique, seuls compétences et projets variant (Q17, Q29) ; un PDF image est refusé avec sa raison et se rabat sur le gabarit neutre | ✅ |
| D3. Ciblage et traduction | Sélection et ordre des éléments selon l'annonce ; traduction champ par champ avec glossaire et validation | CV anglais ciblé sans ressaisie | ✅ |
| D4. Lettre et message | Même moteur ; storytelling de préparation ; ton des prompts revu (pas de jugement dévalorisant sur la reconversion) | Lettres FR et EN validées sur 3 annonces réelles | ✅ |
| D5. Révisions et envoi | Chaque génération dans un chemin immuable avec hash, vérifié au téléchargement ; préremplissage navigateur porté (confirmation avant) ; confirmation d'envoi au retour avec date et canal | Deux générations → deux PDF distincts récupérables ; l'envoi est lié à la révision exacte | ✅ |
| D6. Écran Candidatures | Kanban ou liste dense avec filtres par étape ; dossier en 4 étapes (CV → lettre → envoi → suivi) ; chronologie, notes | Une relance due est retrouvée en moins de 3 clics | ✅ |

### E. Messages

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| E1. Collecte | Gmail lecture seule, plusieurs boîtes ; requête filtrée (`-category:promotions -category:social`…) ; message **enregistré avant toute décision**, de façon idempotente | Une resynchronisation ne retraite rien ; aucun statut ne change sans message enregistré | ✅ |
| E2. Classification | 3 étages : expéditeur → domaine exact de l'employeur (plus de sous-chaîne) → LLM pour l'ambigu ; confiance réelle (plus de valeurs constantes) ; preuve : règle, extrait, auteur | 100 % des décisions ont une preuve lisible ; le digest Quora n'est plus rattaché à « French bee » ; jeu de test issu de l'archive | ✅ |
| E4. Décisions et écran | Transition de candidature appliquée dans la même transaction que la décision ; « ce qui a bougé depuis ta dernière visite » ; correction humaine → nouvelle règle ; corrections conservées comme jeu étiqueté | Aucun changement de statut ne passe inaperçu | ✅ |
| E3. Alertes comme source | Mails d'alerte Indeed, APEC, LinkedIn, WTTJ, Hellowork, Cadremploi → offres via le module `offres` ; erreurs d'import visibles | Au moins une offre Indeed réelle par jour | ⬜ |
| E5. Lecture assistée | Sur le geste de l'utilisateur, Rocky ouvre la fiche d'une offre incomplète dans un navigateur visible sur le poste, l'utilisateur passe lui-même un éventuel défi, Rocky lit le texte affiché (`parse_page`, `enriched`) ; geste « Enrichir » dans la fiche de l'offre ; jamais dans la veille automatique (décision C1, Q6 ; étape ajoutée par la décision D2, Q3) | Une offre Apec incomplète enrichie depuis sa fiche | ⬜ |

### F. Bascule

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| F1. Écrans transverses | 🏠 Aujourd'hui (offres à examiner, dossiers à finir, relances dues, réponses à vérifier, retard de veille) ; ⚙️ Système (état lisible par source, OAuth, planification) ; 📈 Bilan minimal (accusé technique ≠ réponse humaine ≠ entretien ≠ offre, dénominateurs affichés) ; tiroir Rocky | Chaque écran a une action principale claire | ⬜ |
| F2. Recette et bascule | Tests de bout en bout : choisir 3 offres, préparer et confirmer un envoi, retrouver une relance, lire un changement Gmail ; export final de l'ancien Rocky ; retrait de Streamlit, de l'ancien code et des scripts Hugging Face | Nicolas mène sa recherche une semaine entière uniquement dans le nouveau Rocky | ⬜ |

## 5. Hors refonte (plus tard)

- 📈 Bilan complet : vues `analytics_*`, entonnoir par source, piste et langue, périodes et cohortes, export Parquet ; analyse de l'archive.
- Objectif hebdomadaire, série, résumé depuis la dernière visite.
- VPS puis alpha-testeurs : HTTPS, sauvegardes et restauration, veille par compte, validation OAuth Gmail (scope restreint ; jetons limités en mode « Test »).
- Modèle de ML de scoring entraîné sur les données produites (D14) — réalisé à la main par Nicolas.
- Apprentissage manuel d'Alembic sur un autre projet.

## 6. Traçabilité des constats

| Constat (audit Codex / plan v1 / parcours visuel) | Étape |
|---|---|
| PDF de candidature réécrits au même chemin, hash historique faux | D5 |
| Statut Gmail changé avant l'enregistrement du message | E1, E4 |
| Annulation de statut en deux transactions | D1 |
| Veille pouvant rester `RUNNING`, écritures partielles | C6 |
| Offres complètes sous le seuil jetées sans trace | C6, C7 |
| Statut partagé entre profils | Sans objet (D2) + `job_decisions` |
| Absence de migrations, divergence SQLite/PostgreSQL | B2, D5 (PostgreSQL seul) |
| Scheduler et cron redondants | C6 (D12) |
| `repository.py` monolithique, SQL dans `AuthService` | Architecture D13, B3 |
| Score trop précis en apparence, poids statiques | C4, C5 |
| `calculate_match` avec effets de bord | C4 |
| `job_analysis` dans `dashboard` (dépendance inversée) | C3 |
| `_import_links` silencieux | C2, E3 |
| Veille ponctuelle « Data Analyst » notée avec le profil Data Scientist | B5, C4 (pistes) |
| APEC sans filtre de lieu, descriptions incomplètes | C1 |
| Indeed limité (TheirStack, 1 page) | E3 |
| France Travail refusé à chaque veille | C1 (D8) |
| Requête Gmail non filtrée, marqueurs trop larges, sous-chaînes, confiances constantes | E1, E2 |
| CV anglais non ciblé, verrou Canva, LibreOffice | D2, D3 |
| Profils frictionnants (kit anglais obligatoire, doublons FR/EN) | B5 (D2) |
| UI chargée, cartes de 430 px, carrousels, doubles confirmations, `load_data()` doublé | B4, C7, D6, E4, F1 |
| Perte de session au rechargement | B3 (D11) |
| TJM affiché comme salaire, descriptions non formatées | C3 |
| Projets affichés en dictionnaires, doublons de compétences, onboarding permanent | B5 |
| Ton de l'IA sur la reconversion | D4 |
| Taux de réponse gonflé par les accusés, dénominateurs incohérents | F1 (puis §5) |
| Noms de source hétérogènes | C1 |
| Monitoring mêlant notes, config et historique ; retard de veille non signalé | F1, C6 |
| Relances perdues dans les notes | D1, D6 |
| Pas de lint ni de typage ; tests UI en échec | B1 |
| Code mort, imports inutilisés, scripts Hugging Face | Non repris ; retrait en F2 |
| Absence de tests de parcours avant refonte UI | F2 (et tests par écran) |
| Notes de Nicolas (29–30/08) : storytelling, listes déterministes du CV, résumé de description, récupération par plateforme, classification de performance | D4, D2, C3, C1, §5 |

## 7. Validation métier

Après la bascule, mesurer en usage réel : offres examinées parmi les offres captées, offres retenues malgré un
score faible, envois confirmés, relances faites à échéance, réponses humaines par candidature envoyée.
Ne comparer des périodes qu'une fois dénominateurs et qualité des événements fixés.

## 8. Constats en cours de route

*(Les agents notent ici ce qu'ils observent hors du périmètre de l'étape en cours, avec l'étape concernée.)*

- **(A1 → B1, §5 VPS)** Le conteneur `job-assistant-postgres` a `POSTGRES_USER=valeur_de_DB_USER` (gabarit non
  substitué) ; le rôle réel `job_user` est **superutilisateur** et sert à l'application. Le nouveau Rocky
  doit utiliser un rôle applicatif sans privilège de superutilisateur.
  *Résolu en B1 : rôle `rocky_app` sans privilège, vérifié par un test.*
- **(A1 → F2)** `main` a divergé du code en service (78/82 fichiers différents : corrections lint/typage/sécurité
  jamais déployées). La référence de l'ancien Rocky est le tag `rocky-v1-streamlit` ; décider en F2 du sort de `main`.
- **(A1 → D5, B5)** Chemins de documents hétérogènes dans l'ancienne base : absolus (`/data/…`), relatifs au
  répertoire courant (`output/…`, `data/…`), dont un CV de profil de test jamais conservé. Le nouveau Rocky stocke
  des chemins relatifs à une racine de stockage configurée, vérifiés par hash.
- **(A1 → B1)** Les montages bind Docker échouaient (`Resource deadlock avoided`, OSError 35) quand le dépôt était
  sous iCloud. Le dépôt vit désormais dans `~/Developer/` : vérifier en B1 si les montages bind fonctionnent ;
  données PostgreSQL et fichiers du nouveau Rocky en volumes Docker nommés dans tous les cas.
  *Résolu en B1 pour PostgreSQL : montages bind fonctionnels (service `check`), base en volume `rocky-db-data`.*
- **(A2 → B1)** `pyproject.toml` de l'ancien Rocky déclare `testpaths = ["tests"]` : la configuration pytest du nouveau
  Rocky ne doit collecter que `tests/<module>/`, pas les anciens tests à plat.
  *Résolu en B1 : `collect_ignore_glob` dans `tests/conftest.py`.*
- **(A2 → B1)** Le garde-fou `.claude/hooks/guard_paths.py` ne couvre que Claude Code ; Codex ne s'appuie que sur
  `AGENTS.md`. À réévaluer si Codex travaille sur la refonte.
- **(A2 → C4)** Les règles de score de l'ancien Rocky s'appellent `matching-v1` : la version des nouvelles règles
  porte un nom distinct (pas `matching-v2`).
  *Résolu en C4 : `score-2026-09-25.1`.*
- **(B1 → F2)** Le Dockerfile du nouveau Rocky est écrit en ligne dans `docker-compose.yml`, car `Dockerfile` et
  `.dockerignore` à la racine appartiennent à l'ancien Rocky. En F2 : l'extraire en `Dockerfile` et remplacer
  le `.dockerignore`.
- **(B1 → D2, D5)** Le volume nommé des fichiers du nouveau Rocky (CV, lettres) n'existe pas encore : à créer quand
  les premiers fichiers sont écrits.
- **(B1 → à décider avec Nicolas)** `main` avait une CI GitHub (`.github/workflows/ci.yml`) ; la branche `refonte`
  n'en a pas et `.github/` n'est pas au tableau des écritures d'`AGENTS.md`. La vérification ne tourne qu'en local.
  *Résolu en B1 (arbitrage de Nicolas) : `.github/workflows/verification.yml` exécute la même commande que la
  vérification locale. Exiger ce passage avant le merge dans `main` se règle en F2.*
- **(B1 → B2)** Le service `test-db` reste démarré entre deux vérifications et garde son contenu en mémoire :
  l'isolation entre tests (transaction annulée ou schéma recréé) est à définir avec la première migration.
  *Résolu en B2 : un schéma migré par exécution de pytest, supprimé à la fin ; chaque test dans une transaction annulée.*
- **(B2 → B3)** `events` n'a pas encore de compte : B3 ajoute `account_id` et sa clé étrangère vers `accounts`
  par une nouvelle migration.
  *Résolu en B3 : migration `0002`.*
- **(B2 → D6, F1)** Aucune lecture du journal n'existe encore : la chronologie par sujet (`ix_events_subject`)
  s'écrit avec le premier écran qui l'affiche.
  *Résolu en D6 pour les candidatures : `system.events.events_about` et `candidatures/timeline.py` (chronologie du
  dossier) ; reste F1.*
- **(B2 → §5 VPS)** Le déclencheur d'ajout seul protège des erreurs, pas d'un propriétaire qui le désactiverait :
  sur le VPS, envisager que les migrations tournent sous un rôle propriétaire distinct de `rocky_app`.
- **(B2)** Un schéma `test_…` peut rester dans `test-db` si une exécution de pytest est tuée ; sans conséquence
  (`test-db` est en mémoire et se vide à son redémarrage).
- **(B2 → vérification GitHub, §5 VPS)** GitHub annonce que `ubuntu-latest` passera à **Ubuntu 26 à partir du
  19 octobre 2026** (annotation du passage `36047140129`). La vérification tourne dans Docker, donc a priori sans
  effet ; mais **si la vérification GitHub casse à partir d'octobre, explorer d'abord cette piste** (version de
  Docker ou de Compose de la nouvelle image). Contournement immédiat : fixer `runs-on: ubuntu-24.04` dans
  `.github/workflows/verification.yml`. Le VPS de Nicolas tourne aussi sous Ubuntu : même vigilance lors de son
  installation.
- **(B3 → C6)** Sessions et jetons expirés restent en base : purge par une tâche du planificateur.
  *Résolu en C6 : tâche quotidienne du planificateur (4 h), `SqlAuthStore.purge_expired`.*
- **(B3 → B4)** Pas de `favicon.ico` (erreur 404 dans la console) ; les formulaires de mot de passe n'ont pas de champ
  identifiant caché (Chrome le recommande pour les gestionnaires de mots de passe) : à traiter avec la coque.
  *Résolu en B4 : `favicon.svg` ; champ identifiant caché lu depuis le lien sans le consommer.*
- **(B3 → §5 VPS)** Limiter les tentatives de connexion par adresse IP (le verrou actuel est par compte) ;
  changement d'adresse et suppression de compte ; jeton CSRF si un formulaire doit un jour accepter une requête
  d'un autre site.
- **(B3)** Les outils Playwright écrivent leurs traces dans `.playwright-mcp/` à la racine : ignoré par Git,
  à supprimer après usage.
- **(B4 → F2)** La base de développement contient des comptes d'essai : `essai-b4@rocky.local` (créé par Claude,
  en attente) et le compte d'essai de Nicolas sur sa deuxième adresse. À la bascule : nettoyer les comptes d'essai et
  activer le compte principal réel de Nicolas (le journal en ajout seul empêche de les supprimer : prévoir la méthode,
  par exemple une base de production neuve). Les essais de navigateur de Claude utilisent une instance à part
  (application sur le poste, schéma dédié de `test-db`).
- **(B4 → C1, C6)** Données hétérogènes de l'archive : nom de source enregistré comme une URL, télétravail en cinq
  formulations (`Télétravail`, `partial`, `no`…), quasi-doublons d'une même offre sous deux noms d'employeur
  (« Jems Group » / « JEMS »). La déduplication de C6 doit rapprocher les variantes d'un employeur.
  *Résolu en C6 pour les employeurs : clé de rapprochement `match_key` (« Jems Group » = « JEMS »), signal « vue aussi
  sur … » à l'écran en C7 ; aucune fusion (décision C6, Q4).*
- **(B4 → C3)** Descriptions contenant du Markdown (`## **…**`) : à mettre en forme.
  *Résolu en C3 : `formatted_description` (HTML et Markdown en lignes et puces).*
- **(B4 → C7)** Décisions persistées (`job_decisions`) et journalisées, y compris annulations et changements ;
  suppression de `rocky/offres/prototype.py`, `prototype_offers.json` et de `docs/procedures/b4-prototype/`.
  *Résolu en C7 : `job_decisions` en ajout seul, changements et annulations journalisés ; prototype supprimé.*
- **(B4 → C7, VPS)** Une touche frappée pendant l'arrivée d'un fragment HTMX se perd : envoyer les panneaux de motifs
  avec la carte, ou sérialiser les requêtes (`hx-sync`), si la latence du VPS le rend sensible.
- **(B4 → C7)** HTMX fait hériter `hx-swap` et `hx-target` de ses ancêtres : un élément placé dans un conteneur qui
  en déclare un autre doit déclarer les siens (bug « Revenir » trouvé par Nicolas, corrigé en B4). D6 confirmé :
  HTMX retenu par Nicolas, cinq critères tenus.
  *Tenu en C7 : `hx-swap` explicite sur chaque cible, test de non-régression gardé.*
- **(B5 → C3)** Les compétences et leurs alias sont **propres à chaque compte** (décision B5, Q2) : la détection des
  compétences d'une annonce se fait avec les termes du compte (`skill_terms`, `normalize_term`), pas avec un
  dictionnaire global. L'ancien `SKILL_ALIASES` n'a servi qu'au réimport.
  *Résolu en C3 : `account_skills`, lues par `profil.web.skills_of` (cas d'usage du profil).*
- **(B5 → C4)** Caractéristiques disponibles pour le score (D14) : drapeau « clé » et niveau des compétences,
  compétences liées aux expériences et projets (preuves), intitulés, mots-clés et mots exclus des pistes.
  *Résolu en C4 : lues par `scoring_profile` et gardées dans les `features` du score.*
- **(B5 → C6)** Suppression définitive d'une piste : à interdire dès qu'une offre y est rattachée (seul l'archivage
  reste alors possible).
  *Résolu en C6 : `offer_tracks.track_id` en `RESTRICT`, message « archive-la plutôt ».*
- **(B5 → après C6)** Lieux des pistes en libellés libres jusqu'à C6 ; lieux structurés (ville + rayon, région, pays)
  visés pour la version finale.
- **(B5 → D2)** Le gabarit HTML/CSS du CV **reproduit le design du CV actuel de Nicolas** (validation côte à côte).
  Import d'un CV PDF à l'onboarding pour un nouvel utilisateur : lu par le LLM de Rocky, proposé champ par champ,
  ajouté à l'onboarding avec D2.
- **(B5 → D2, D5)** **Rendu stable** : le même contenu donne le même PDF ; un test de non-régression visuelle
  (rendu de référence) empêche un CV de dériver en silence au fil des régénérations (remarque de Nicolas).
- **(B5 → F2)** Réimport du profil de Nicolas dans son compte réel avec le fichier relu
  (`docs/procedures/b5-reimport/`).
- **(B5 → `system`, LLM)** Le LLM de Rocky passera de Groq à **Gemini 3.5 Flash Lite** (Nicolas, 25/09) : le plan
  (§3, Adaptateurs) et `AGENTS.md` (§7) citent Groq, à corriger quand l'adaptateur LLM naîtra.
  *Résolu en C3 : adaptateur `rocky/system/llm.py` (Gemini), plan §3 et `AGENTS.md` §7 corrigés.*
- **(B5 → C3)** Un nom « X (Y) » (« Traitement du langage naturel (NLP) ») ne répond qu'à lui-même (Q9 compare les
  noms entiers). *Tranché par Nicolas (25/09) : règle inchangée ; une variante utile s'ajoute comme alias*
  (« Traitement du langage naturel » alias de NLP).
  *Complété en C3 (Nicolas, Q4) : dans une annonce, « X (Y) » répond aussi à X et à Y ; la comparaison des noms du
  profil (Q9) ne change pas.*
- **(C1 → E3)** Indeed/TheirStack n'est pas porté (quota épuisé, API payante) : Indeed arrive par ses alertes e-mail.
- **(C1 → C2, C7)** **Enrichissement** d'une offre incomplète (APEC refuse son détail, LinkedIn n'en donne pas, Adzuna
  un extrait). *Tranché par Nicolas (25/09)* : deux voies **coexistantes**, (1) **lecture assistée** : sur son geste,
  Rocky ouvre la fiche dans un navigateur visible, l'utilisateur passe lui-même un éventuel défi, Rocky lit le texte
  affiché, une offre à la fois, jamais dans la veille automatique ; (2) **description collée** par l'utilisateur.
  Moteur en C2 (même mécanique que l'import d'URL), geste « Enrichir » dans la fiche de l'offre en C7. Aucun
  navigateur automatisé pour passer DataDome (Q5). La lecture assistée ne marche que sur le poste (pas de VPS sans
  écran) : la description collée reste la voie universelle.
- **(C1 → C3)** Adzuna : un TJM freelance arrive dans `salary_min` (450 pour « Data Analyst - Freelance »), un salaire
  annuel ailleurs ; aucune période n'est stockée en C1, C3 les distingue.
  *Résolu en C3 (Q5) : période écrite d'abord, sinon déduite du montant et marquée.*
- **(C1 → C3)** Apec donne contrat (`typeContrat`, ex. `101888`) et télétravail (`idNomTeletravail`) en **codes
  sans libellé** : laissés vides en C1, à décoder par un référentiel Apec, jamais devinés. Descriptions Wellfound en
  Markdown ; offres Wellfound anciennes encore en ligne (publiée en 2024).
  *Résolu en C3 (Q8) : référentiel public capturé, table `CONTRACT_LABELS` / `REMOTE_LABELS` vérifiée par un test.*
- **(C1 → C4, C6)** Welcome to the Jungle ne filtre pas le lieu (offres de New York, Austin, Londres pour « Data
  analyst ») ; Wellfound sert une page pour un lieu qu'il ne connaît pas (« Eure et Loire »). Le lieu doit donc peser
  dans le score ou marquer l'offre, pas seulement la requête.
  *Résolu en C4 pour le score (Q9, Q15 : hors zone, à l'étranger) ; le filtrage de la veille reste à C6.*
  *Résolu en C6 : aucune offre n'est filtrée par la veille (invariant « aucune offre jetée ») ; une offre à l'étranger
  est gardée, plafonnée par le score.*
- **(C1 → C6)** `collect` déduplique par source seulement ; la déduplication entre sources et le rattachement aux
  pistes (appeler la collecte piste par piste) sont à faire en C6. Durée mesurée : 48 s pour une piste de 6 requêtes
  avec détails (pause d'une seconde par site).
  *Résolu en C6 : `collect` garde les requêtes de chaque offre (`found_by`), rattachées aux pistes par `track_queries`.*
- **(C1 → Nicolas, B5)** Lieu « Eure et Loire » dans les deux pistes : Apec ne connaît qu'« Eure-et-Loir » (requêtes
  sautées et signalées par `rocky-admin sources`).
- **(C1 → F1)** État des sources à l'écran ⚙️ Système : reprendre `CollectionReport` et `report_lines`.
- **(C1 → §5 VPS)** Sur un VPS (IP de centre de données, plusieurs comptes), réévaluer le volume par compte et la
  tolérance de LinkedIn et Wellfound (Cloudflare) ; la règle d'arrêt reste.
- **(C1 → C6)** Une panne sur une requête (erreur 5xx, délai dépassé, référentiel de lieux Apec indisponible) arrête
  les requêtes suivantes de la source ; les offres déjà reçues sont gardées. Choix de C1 (pas de réessai, un site en
  erreur est probablement en panne) : la veille partielle de C6 dira s'il faut plutôt poursuivre et marquer les
  requêtes en échec (revue de code du 25/09).
  *Tranché en C6 (Nicolas, Q9) : choix de C1 conservé, la veille est partielle.*
- **(B5 → F2)** Le script de réimport (`docs/procedures/b5-reimport/extract_profile.py`) ne fusionne que
  « Traitement du langage naturel (NLP) » dans NLP : l'alias « Traitement du langage naturel » décidé le 25/09 n'y
  est pas. Au réimport dans le compte réel, l'ajouter au fichier relu ou au script (revue de code du 25/09).
- **(B5 → C3)** Règle de reconnaissance des compétences dans les annonces à trancher en C3 : un nom « X (Y) » ne
  répond qu'à lui-même, et rien ne signale à l'utilisateur qu'un alias manque (alias masqués à l'écran). Une autre
  compétence de cette forme (« Apprentissage automatique (ML) ») aurait le même trou (revue de code du 25/09).
  *Résolu en C3 (Q4) : X et Y répondent dans les annonces, sans alias à ajouter.*
- **(C2 → §5 VPS)** La vérification anti-SSRF résout l'hôte avant la requête, puis le client HTTP le résout à
  nouveau : un DNS qui change de réponse entre les deux (*rebinding*) passerait. Sur le VPS, ajouter une règle
  réseau (pare-feu sortant ou proxy) qui interdit au conteneur de joindre les adresses privées.
- **(C2 → E3)** Les liens des alertes passent par `import_link` : chaque lien en échec garde sa raison (fin de
  `_import_links`). Un lien d'alerte porte souvent un jeton de suivi : il n'est jamais journalisé.
- **(C2 → C7)** Geste « Enrichir » : la lecture assistée (navigateur visible, sur le poste) donne le HTML affiché à
  `parse_page`, puis `enriched` ; le collage dans la fiche utilise `with_pasted_description`. Le formulaire de
  collage de l'import crée l'offre depuis le texte seul (lien, intitulé, employeur) : les faits déjà lus d'un
  aperçu incomplet ne sont pas repris tant que rien n'est enregistré.
- **(C2 → C6)** Une page importée a pour identifiant son adresse canonique ; la veille garde l'identifiant de la
  plateforme (numéro LinkedIn, référence WTTJ). La déduplication entre import et veille doit comparer les adresses.
  *Résolu en C6 : `SqlStore.find` cherche par source et identifiant, puis par adresse.*
- **(C2 → C3)** Faits bruts du JSON-LD à interpréter : `employmentType` (`FULL_TIME`, `CONTRACTOR`),
  `jobLocationType` (`TELECOMMUTE`), période du salaire (`YEAR`, `DAY`), date limite (`deadline`). Les clés
  `intitule` et `enseigne` du détail Apec viennent d'un jeu reconstruit (Apec refuse son détail) : à vérifier dès
  qu'une réponse réelle est obtenue.
  *Résolu en C3 pour les codes (décodés par source) ; la vérification des clés du détail Apec reste ouverte.*
- **(C2 → C7, F1)** La coque boost tous les liens (`hx-boost`) : tout écran atteint par un lien doit choisir
  fragment ou page par `wants_fragment` (`system.shell`), jamais par `is_htmx` seul (bug de C2 trouvé à l'essai).
  *Tenu en C7 : l'écran Offres n'utilise que `wants_fragment`.*
- **(C3 → C4)** Caractéristiques pour le score (D14) : compétences du compte avec leur importance (éliminatoire, un
  plus, mentionnée) et leur preuve, conditions, contrats et télétravail dans le vocabulaire des préférences, salaire
  avec période (comparable à `min_salary_eur` / `min_daily_rate_eur`), expérience, langues ; `RULES_VERSION` à garder
  avec le score. Une période **déduite** du montant doit peser moins qu'une période écrite.
  *Résolu en C4 : tout est lu par le score ; période déduite = poids du salaire divisé par deux, confiance moyenne.*
- **(C3 → C6, C7)** L'analyse et le résumé ne sont pas enregistrés : à stocker avec l'offre (analyse recalculable,
  résumé gardé une fois demandé pour ne pas rappeler le modèle).
  *C6 : l'analyse n'est pas stockée, elle se recalcule (2 s pour 517 offres) ; le résumé reste pour C7.*
  *Résolu en C7 : résumé gardé dans `offer_summaries`, périmé quand la description change.*
- **(C3 → C2, C6)** Import Hellowork : le CDI n'est que dans le titre de la page (le JSON-LD donne `FULL_TIME`) ; lire
  aussi le `<title>` ou un champ de la page si le contrat manque (3 écarts de la mesure C3).
- **(C3 → `profil`)** `normalize_term` réduit « C++ » et « C# » à « c » : une compétence de ce nom répondrait à la
  lettre « C » d'une annonce. À traiter si un compte déclare ces langages.
- **(C3 → Nicolas)** Résumé réel à essayer : ajouter `ROCKY_GEMINI_API_KEY` au `.env`, relancer l'application
  (`docker compose up -d --build --wait app`), importer une annonce, « Résumer l'annonce ».
  *Résolu en C3 : clé ajoutée par Nicolas ; un résumé réel, fidèle au texte (décision C3, clôture).*
- **(C4 → C6)** Le score n'est pas enregistré : table des scores (une ligne par offre et par piste, `Score.to_json`,
  `RULES_VERSION`) à créer avec l'offre et ses rattachements, dans la même transaction.
  *Résolu en C6 : `offer_scores`, un score courant par offre et par piste, avec `inputs_hash` (décision C6, Q6).*
- **(C4 → C5)** Calibrage (mesure `docs/procedures/c4-mesure/`) : confiance faible pour 65 % des annonces (médiane des
  preuves 1,4 point, seuil 2 ; 11 compétences prouvées sur 52) ; haut du classement saturé à 100 ; marge étroite de
  la « Data Protection Analyst » avec un profil qui la favorise (47 < 50). Corrélation de rang v1 / C4 : 0,08.
- **(C4 → C3, C5)** Fausses exigences hors profil de l'analyse : « Maîtrise de l'anglais obligatoire » (l'anglais est
  au profil, C1) et « This posting is representative of multiple roles… » retirent chacune un point de preuve.
- **(C4 → Nicolas, B5)** Préférences du profil réel : aucun mode de télétravail (composante toujours absente), pas de
  « Freelance » (une mission vaut 0 au contrat), pas de TJM minimum, aucun mot exclu dans les pistes (« Stage Data
  Scientist » n'est pas plafonnée).
  *Résolu (Nicolas, 25/09) : préférences complétées. La mesure C4 a été faite avant : la relancer au début de C5.*
  *Mesure relancée le 28/09 (`docs/procedures/c4-mesure/`, point de départ de C5) : la 1193 passe de 29 à 44 (< 50) ;
  Spearman v1 / C4 0,10 ; confiance faible toujours pour 263 annonces sur 404. Les pistes n'ont toujours aucun mot
  exclu (« Stage Data Scientist » à 46, non plafonnée).*
- **(C4 → C5)** Composantes logistiques sans preuve de métier (mesure du 28/09) : quand compétences et intitulé sont
  faibles, contrat, lieu et salaire pleins, renormalisés faute d'autres informations, portent le score (1193 à 44,
  1030 « Sourcing » à 24 avec compétences et intitulé à 0). Le télétravail, les trois modes étant acceptés, vaut 1 dès
  que l'annonce en parle sans rien distinguer.
- **(C5 → `profil`)** L'écran de profil laisse créer deux compétences qui ne diffèrent que par un espace ou la casse
  (« ML Flow » / « MLFlow », « HuggingFace » / « hugging face », vus le 28/09 et fusionnés à la main par Nicolas) :
  une annonce ne répond qu'à l'une des deux. Proposer l'alias quand le nom replié correspond à une compétence existante.
- **(C5 → `profil`)** Le champ « Mots exclus » (et les autres listes des pistes) attend une valeur par ligne, sans le
  dire : « senior, lead, staff… » saisi sur une ligne devient un seul terme, qui ne se trouve dans aucun intitulé
  (29/09). Son aide dit « les annonces qui les contiennent sont écartées », faux depuis C4 : un mot exclu dans
  l'intitulé plafonne le score, dans la description il est seulement signalé.
- **(C5 → `profil`)** Séniorité : un réglage « niveau visé » (junior, confirmé, senior) serait la bonne forme ; en C5,
  Nicolas passe par les mots exclus de chaque piste (décision C5, Q23).
- **(C5 → `offres`, analyse)** Secteur ou domaine de l'annonce (« Financement structuré », « Cash management ») : aucune
  composante ne le lit ; motif « secteur » cité 10 fois dans les annotations C5 (décision C5, Q15).
- **(C5 → C7, puis recalibrage)** Les règles `score-2026-09-29.2` sont un point de départ (décision C5, Q29) : les
  décisions réelles de Nicolas à l'écran Offres (C7, étiquettes D14) serviront à les affiner. Directions relevées : le
  contrôle reste à parité avec la v1 sans la dépasser (annonces au bon intitulé mais pauvres en compétences du profil,
  haut du classement saturé à 100) ; une annonce qui demande surtout des compétences absentes du profil (751,
  « Financement structuré ») reste haute, faute de lire le poids de ces compétences dans l'annonce (Q30) ; une annonce
  aux compétences implicites (438, « accessibles mais pas toutes nommées ») reste basse, l'analyse ne lisant que les
  termes du profil (Q34). Avec les mots exclus de Nicolas et la règle de l'étranger, 180 des 404 annonces de la mesure
  sont plafonnées : à surveiller dans l'écran Offres (C7).
- **(C5 → C7, recalibrage)** Séniorité et expérience (décision C5, Q35) : l'expérience pertinente compte les emplois
  liés à n'importe quelle compétence de l'annonce ; pour un profil en reconversion (emplois liés seulement à des
  compétences métier), elle vaut 1 dès 3 ans demandés, et elle ne pèse que 3. Leviers : ne compter que les emplois liés
  à une compétence technique, relever le poids (simulé : poids 8, 3 des 13 « trop hautes » sortent des 20 premières),
  réglage « niveau visé » du profil (ci-dessus). À trancher sur les décisions réelles.
- **(C4 → après C6)** Lieux structurés : une ville d'Eure-et-Loir ne répond pas à « Eure et Loire » ; un pays absent
  (LinkedIn, Wellfound) est lu comme la France, avec le marqueur « pays non précisé ».
- **(C4 → profil)** Permis et habilitation absents du profil : une condition bloquante plafonne toujours le score
  (Q6). Les ajouter au profil si le cas se présente.
- **(C4 → C3, `system`, à décider avec Nicolas)** Résumé Gemini : « Gemini est en panne (HTTP 503) » à deux essais de
  Nicolas le 25/09 (serveur de Google surchargé, pas une erreur de Rocky). Options : un seul réessai sur 503 (la décision
  C3 dit « aucun réessai ») ; message « surchargé, réessaie dans un instant » plutôt que « en panne ».
  *Résolu (Nicolas, 25/09) : le projet Google AI Studio était en offre gratuite ; passé sur le compte de facturation,
  le résumé répond. Rien à changer dans Rocky.*
- **(C6 → C1, à décider avec Nicolas)** Première veille réelle (29/09) : LinkedIn répond 429 après 68 offres (requêtes de
  deux pistes). Si le refus revient chaque jour, chaque veille sera partielle (comme les 54/54 de l'ancien Rocky), ce
  qui est exact mais use le signal. Leviers : moins de requêtes vers LinkedIn (intitulés, lieux), ou LinkedIn par les
  alertes e-mail (E3). Observer quelques veilles avant de trancher.
  *Tranché par Nicolas (29/09, décision C1, Q7) : lieux nettoyés (18 requêtes), pause de 10 s vers LinkedIn ; un seul
  lieu par intitulé seulement si le 429 persiste. Alertes e-mail en E3 : complément (nouvelles annonces, faits en plus
  sur une annonce connue), jamais un repli pour LinkedIn (Q8).*
- **(C6 → C7)** 350 offres incomplètes sur 517 à la première veille (Adzuna, Apec, LinkedIn) : leur score est bas faute
  de texte. Le geste « Enrichir » et le filtre « incomplètes » de C7 en sont la réponse.
  *Résolu en C7 : filtre « Incomplètes » (au-dessus et sous le seuil) et « Coller la description » (score recalculé).*
- **(C6 → C7)** L'écran Offres lit `job_offers`, `offer_tracks` et `offer_scores` (`SqlStore.current_score`) ; « vue aussi
  sur … » par `match_key` ; une décision garde une copie du score affiché (Q6, D14) ; le bouton « Supprimer
  définitivement » d'une piste qui a des offres pourrait être masqué (le refus est déjà expliqué).
  *Résolu en C7 : écran branché sur ces tables, « vue aussi sur … » par `match_key`, copie du score dans chaque
  décision ; le bouton de suppression est renvoyé à `profil`.*
- **(C6 → F1)** Le bandeau de veille (retard, en cours, échec) va dans 🏠 Aujourd'hui ; ⚙️ Système lit `watch_runs` et
  `watch_run_sources` (état par source, requêtes sautées, détail arrêté).
- **(C6)** Un import par URL qui écrirait la même offre au même instant qu'une veille heurte la contrainte d'unicité
  (erreur visible, pas de donnée incohérente) : réessayer suffit. Les journaux `INFO` des modules ne sont pas affichés
  par uvicorn (seuls avertissements et erreurs, avec leur trace) : à régler avec la journalisation du VPS.
- **(C7 → F2)** Les décisions de C7 (compte d'essai, base de développement) sont un essai : avant de repartir sur une
  base neuve, les **exporter dans un fichier** (`job_decisions` et leurs événements) pour une analyse éventuelle
  (décision C7, Q9).
- **(C7 → `profil`)** Le bouton « Supprimer définitivement » d'une piste qui a des offres pourrait être masqué (le refus
  est déjà expliqué) ; laissé tel quel en C7 (Q14).
- **(C7 → D2)** Lecture assistée d'une offre incomplète (navigateur visible sur le poste, décision C1, Q6) : reportée,
  Playwright arrive en D2. En C7, seule la description collée enrichit une offre (Q5).
  *Tranché en D2 (Nicolas, Q3) : hors D2 (autre logique métier), nouvelle étape E5 avant F1 ; Playwright est disponible
  depuis D2 pour le rendu PDF.*
- **(C7 → recalibrage)** Les décisions réelles (étiquettes D14 avec la copie du score) sont la matière des leviers
  notés en C5 (séniorité, compétences hors profil, plafonds).
- **(C7)** « Vue aussi sur … » : chaque offre d'un doublon se décide séparément (Q4) ; copier la décision sur l'autre
  offre (auteur `rule`) ou la sortir de la file, si la double décision gêne à l'usage.
- **(C7 → VPS)** Frappes perdues (constat B4 → C7) : toujours ouvert. `hx-sync` n'y répond pas (la touche perdue ne
  déclenche aucune requête) ; parade à juger sur le VPS : panneaux de motifs envoyés avec la carte.
- **(C7)** La liste se calcule en mémoire sur toutes les offres du compte (13 ms pour 520) : passer à une requête filtrée
  en SQL si un compte dépasse quelques milliers d'offres.
- **(C7 → étape à placer, avant le recalibrage)** **Lieux structurés, mesuré le 29/09** : les pistes de Nicolas ont pour
  lieux « Ile de France » et « Eure et Loir », mais le score cherche le mot du lieu dans celui de l'annonce (`_zone`) ;
  « Paris 01 - 75 », « Levallois-Perret », « Courbevoie - 92 », « Chartres - 28 » n'y répondent pas. Sur 1 304 scores
  (652 offres × 2 pistes), la composante lieu vaut 1 dans 156 cas, 0,3 (hors zone) dans 698 ; **78 offres sont entre 40
  et 49 avec un lieu « hors zone »**, pour 60 au-dessus du seuil. Remplacer les régions par des villes dans les pistes
  n'est pas la parade : les lieux des pistes font aussi les requêtes de la veille (Apec sur la région entière, volume
  LinkedIn, C1 Q7) et les banlieues resteraient hors zone. Correction : un référentiel (communes, départements →
  région) pour qu'une région couvre ses villes dans le score ; nouvelle `RULES_VERSION`, mesures C4/C5 relancées.
  Suite des constats (B5 → après C6) et (C4 → après C6). À trancher à la revue de cette section.
- **(C7, à trancher à la revue)** Motif « autre » de l'essai : « date de candidature dépassée ». Une annonce dont la date
  limite est passée pourrait être signalée à l'écran (la date limite est déjà lue par l'analyse C3), voire écartée par
  une règle (auteur `rule`, Q2) ; ou un motif « date limite dépassée » ajouté à « Écarté ».
- **(D1 → `offres`)** La touche `u` de l'écran Offres annule la dernière décision du compte, y compris l'« Intéressé »
  écrit par « Préparer la candidature » : le dossier reste alors ouvert sur une offre revenue à sa décision d'avant.
  Pas d'état contradictoire (le dossier ne dépend pas de la décision après sa création), mais le signal D14 est
  retiré. Si cela gêne à l'usage : exclure de `u` les décisions portant `application_started`, ou prévenir.
- **(D1 → D6)** La date limite de l'offre (lue par l'analyse C3) pourrait borner l'échéance proposée (« Finir le
  dossier », « Envoyer la candidature ») ; non utilisée en D1. Dans la fiche d'offre, après « Préparer », seule la
  liste des offres est rafraîchie (`offers-changed`) : la ligne « Décision : … » de la fiche et les compteurs
  attendent le prochain affichage. Le changement d'étape de la liste brute passe par un menu et un bouton.
  *Résolu en D6 (Q8) : l'échéance proposée avant l'envoi s'arrête à la date limite (`offres.web.offer_deadlines`),
  affichée dans la liste et le dossier ; « Préparer » quitte la fiche pour le dossier (D3, Q25), la fiche se relit en
  entier ; le menu d'étape de la liste part en un geste.*
- **(D1 → E4, F1)** L'accusé de réception est un fait du dossier, pas une étape (D1, Q1) : à enregistrer par E. Un
  passage automatique à « Sans réponse » après un délai sans message, et toute transition automatique, passent par
  `automatic_transition_allowed` (jamais en arrière, jamais hors d'une issue).
- **(D2 → D3)** La **stack** d'un projet est stockée une seule fois, sans version anglaise (B5) : le CV anglais montre
  « analyse de sentiment », « base vectorielle »… À traiter avec la traduction champ par champ.
- **(D2 → Nicolas)** Compétences du Canva classées « métier » dans le profil (HuggingFace, MLFlow, Transformers,
  IA générative, Architecture engineering) : un groupe de compétences techniques ne peut pas les contenir (Q9). Harness
  n'est pas au profil. Les passer en « techniques » (effet sur le score) ou les laisser hors du CV : à trancher.
- **(D2 → Nicolas)** « 37 ans » : l'âge demande la date de naissance, absente du profil ; rien n'a été inventé.
- **(D2)** Une zone du gabarit déduit a une ligne d'air sous elle : un texte un peu plus long que celui du Canva peut
  toucher l'élément dessiné juste en dessous (bord d'une carte projet) sans être signalé comme débordement.
- **(D2 → D3, D4)** Le rendu d'un gabarit déduit reprend les conventions du Canva de Nicolas (« période : intitulé
  - employeur - », école soulignée, puces à amorce en gras) : un autre design peut demander d'autres recettes.
- **(D2 → à reprendre, avant F2)** Étape validée avec des limites (décision D2, clôture) : rendu des blocs projets
  approximatif (retours à la ligne, écarts, « : » des noms de projet) ; gabarit déduit mis au point sur un seul design ;
  rangement des lignes par le modèle variable d'un appel à l'autre (règles déterministes à éprouver sur d'autres CV) ;
  gabarit neutre trop court pour un parcours long (CV anglais de Nicolas sans CV anglais importé : 77 mm de trop).
  À affiner proprement dans une étape dédiée.
- **(D2 → Nicolas)** Ordre des projets du CV maître (Water Potability avant Pilotage, inverse du Canva) : à vérifier.
- **(D3 → D6 ou F1)** Les gabarits ne se suppriment pas : le compte de Nicolas en a 19 (dont 13 essais de mise au point
  de D2). Ils sont repliés sous « Autres gabarits » dans Profil & kit (D3) ; prévoir de retirer un gabarit inactif.
  *Résolu en D6 (Q8) : un gabarit inactif se supprime après confirmation (`profil.cv_template_deleted`).*
- **(D3 → plus tard, remarque de Nicolas)** CV français d'une candidature : le texte du bloc projet « Pilotage
  d'association sportive » sort visuellement de sa carte sans être signalé. Même famille que les limites des blocs
  projets notées à la clôture de D2 (zone mesurée plus large que la carte dessinée).
- **(D3 → D4, D5, D6)** Parcours du dossier (décision D3, Q25, Q26) : « Prête à envoyer » veut dire « CV prêt » tant
  que la lettre n'existe pas (D4 tranchera) ; les envois confirmés en D3 n'ont ni canal ni révision (D5 les accepte tels
  quels) ; raccourci « Intéressé et préparer » depuis le mode tri, 4e étape « Suivi » : D6.
  *Résolu en D6 : 4e étape « Suivi » ; « Valider et préparer la candidature » (touche `d`) dans le panneau « Pourquoi
  intéressé ? » du tri.*
- **(D3 → Nicolas)** Le CV Canva français finit la formation Jedha par « restitution des résultats. ` » (accent grave en
  trop) : il passe tel quel dans le CV anglais. À corriger dans Canva puis réimporter.
- **(D3 → plus tard, idée de Nicolas)** Quand une traduction déborde de sa place dans le gabarit, Rocky pourrait
  **proposer lui-même une version raccourcie** qui y tient (mesure du débordement → demande de reformulation plus courte
  → nouvelle mesure), à valider comme les autres ; aujourd'hui l'erreur nomme la zone et l'utilisateur corrige.
- **(D2 → bêtas, §5)** Adapter aussi les expériences et les formations d'un CV importé à l'offre (décision D2, Q34) :
  seulement si les bêtas en montrent le besoin ; aujourd'hui, le CV importé est tenu pour à jour.
- **(D2 → F2, §5 VPS)** Le dépôt GitHub est **public** et n'a **aucune licence**. Aucune dépendance AGPL n'est ajoutée
  (décision D2, Q25) ; choisir une licence avant d'ouvrir Rocky à d'autres utilisateurs. Les données personnelles
  (photo, gabarits dérivés, rendus de CV) ne sont jamais versionnées.
- **(D4 → D5)** Le PDF de la lettre est recalculé à chaque téléchargement et porte la **date du jour** : deux
  téléchargements à des jours différents donnent deux PDF différents. La révision immuable de D5 doit figer la lettre
  envoyée (date comprise) ; « Envoyée avec la version du … » se déduit aujourd'hui des dates (décision D4, Q20).
- **(D4 → D6, remarque de Nicolas à la recette du 04/10 : « le parcours est juste horrible »)** Parcours de la
  candidature à reprendre en entier avec l'écran Candidatures : page du dossier très longue (CV, lettre, envoi
  empilés), chaque paragraphe de la lettre montré deux ou trois fois (« Ta lettre », « Version de Gemini », « Ma
  version »), gestes dispersés (accord, adaptation, aperçu, validation, « Lettre prête »), langue de la lettre et du
  message par des liens en haut de l'étape. Le fonctionnement (données, transactions, contrôles) est validé ; seule la
  présentation est à refaire.
  *Repris en D6 (Q2–Q4) : une étape à la fois, un seul texte par paragraphe avec le sélecteur « Ta lettre · Gemini »
  rendu par le serveur, une langue par dossier. Jugement de Nicolas à la recette de D6.*
- **(D4 → plus tard, prompt engineering)** Les consignes de Gemini pour la lettre (`ADAPT_INSTRUCTIONS`,
  `rocky/candidatures/letter.py`) sont une première version : les régler **bloc par bloc** (ouverture, parcours,
  apports, pourquoi vous, conclusion), sur les choix réels de Nicolas (paragraphes gardés ou remplacés, gardés comme
  données D14 avec la version proposée).
- **(D4 → Nicolas, recette)** Listes des formules convenues et du ton à éviter (`rocky/candidatures/letter.py`,
  `FORMULAS_TO_AVOID`, `TONE_TO_AVOID`) : première version à valider par Nicolas sur les lettres réelles (décision D4,
  Q8) ; toute modification change `CHECKS_VERSION`.
- **(D4 → plus tard)** Le message d'accompagnement n'est pas collé par Rocky dans les formulaires : le préremplissage
  (D5) pourra le proposer dans le champ libre, toujours avec confirmation.
- **(D4 → D5, F2)** Clôture de D4 (Nicolas, 04/10) sur 2 lettres françaises réelles : la lettre anglaise d'un dossier et
  le message d'accompagnement n'ont été éprouvés que dans l'essai navigateur. Les refaire sur des offres réelles à la
  recette de D5 (envoi lié à la révision exacte) ou de F2.
- **(D5 → §5 VPS)** Le préremplissage passe par le **poste Rocky**, lancé sur l'ordinateur (`uv run rocky-poste`) : sur
  un VPS sans écran, il n'existe pas ; l'utilisateur ouvre le site et télécharge les PDF générés. À revoir avec le
  déploiement (poste sur l'ordinateur de l'utilisateur joint par le VPS, ou rien).
- **(D5 → E5)** Le poste est l'adaptateur « navigateur visible » de la lecture assistée : E5 lui ajoute une demande
  (ouvrir une fiche, laisser passer un défi, rendre le texte affiché) à côté de `/preremplir`.
- **(D5)** Un PDF écrit avant une transaction qui échoue reste dans le stockage sans ligne (adressé par son hash, sans
  effet) : aucune purge en D5 ; à prévoir avec les sauvegardes du VPS si le volume compte.
- **(D5 → D6)** L'étape Envoi s'allonge (PDF générés, préremplissage, confirmation, message) : à reprendre avec le
  parcours du dossier en D6 (constat D4 → D6).
  *Repris en D6 : trois temps numérotés (PDF, dépôt et message, confirmation sur place).*
- **(D5 → B1, vérification)** La vérification globale prend 1 min 50 (tests 104 s), proche de la limite de 2 min :
  rendus Chromium des tests d'envoi et de lettre. Si elle la dépasse : partager un rendu par module (comme D3) ou
  paralléliser pytest.
  *D6 : 1 min 49 (1 166 tests) ; après la recette (aperçus en image), 1 min 51 à 1 min 58 (1 169 tests) : marge trop
  mince, à traiter avant E1 (un rendu partagé par module comme D3, ou pytest en parallèle avec une dépendance justifiée).*
  *Résolu en E1 (Nicolas, Q1) : pytest en parallèle (`pytest-xdist`, `pytest -n auto` dans le service `check`) ;
  1 min 47 → 1 min 03 à 1 min 10 (1 169 tests, 8 processeurs pour Docker). Un paramètre de test doit avoir un identifiant
  stable (les workers comparent leurs collectes) : `ids=` explicites quand la valeur change d'une exécution à l'autre.*
- **(D5 → Nicolas)** Le poste ne reconnaît que des champs vides nommés par leurs attributs ou libellés usuels : sur les
  formulaires des ATS (Workday, Greenhouse, Lever, Taleo…), le rapport dira ce qui reste à faire. Des sélecteurs propres à
  une plateforme s'ajoutent si l'usage le demande.
- **(D5 → plus tard, recette de Nicolas du 04/10)** Le **préremplissage est en sommeil** : échec sur 2 annonces réelles
  sur 2 (les sites des recruteurs n'affichent pas de formulaire tout de suite et passent par leurs propres connexions).
  Code gardé et testé, marqué « DORMANT », fermé par `candidatures.web.PREFILL_ENABLED`. Le parcours de l'envoi devient :
  générer les PDF, ouvrir l'annonce chez le recruteur, remplir soi-même, confirmer « J'ai envoyé ma candidature ». À
  reprendre plus tard, peut-être avec la lecture assistée (E5), qui a le même besoin d'un navigateur sur le poste.
- **(D6 → F1)** 🏠 Aujourd'hui « relances dues » : reprendre `candidatures.web.rows_of` et `rules.tabs_of` (onglet
  « À faire ») plutôt qu'une seconde lecture des dossiers.
- **(D6)** La page du dossier recalcule le CV ciblé, la lettre et l'envoi pour n'afficher qu'une étape (`_dossier`,
  `_dossier_page`) : rapide en local ; à mesurer sur le VPS, et ne calculer que l'étape montrée si c'est lent.
- **(D6 → E4)** Une transition écrite par une règle ou l'IA apparaît dans la chronologie avec « par une règle » / « par
  l'IA » (`timeline._BY`) ; E4 ajoute ses types d'événements à `timeline.LINES` (test `test_timeline.py`).
- **(E1 → E2)** Le seul point d'entrée des décisions est le crochet `app.state.messages_collected` (identifiants des
  messages validés en base) ; un crochet en échec est journalisé, les messages restent. E2 doit donc aussi reprendre les
  messages enregistrés sans classification (absence de ligne de décision), pas seulement ceux du crochet.
- **(E1 → E2, E3)** La requête *alertes* prend tout `from:linkedin.com` : notifications du réseau comprises (messages de
  recruteurs utiles, mais aussi du bruit). À mesurer à la recette d'E1 ; resserrer sur les adresses d'alerte
  (`QUERIES_VERSION`) si le bruit gêne.
- **(E1 → F1)** ⚙️ Système : état des boîtes et des collectes (`mailboxes`, `mail_syncs`, `MessagesService.state`).
- **(E1 → §5 VPS)** `ROCKY_SECRET_KEY` se sauvegarde avec la base : sans elle, les jetons scellés ne s'ouvrent plus et
  chaque boîte est à reconnecter. Validation de l'application Google (scope restreint `gmail.readonly`) avant les
  alpha-testeurs.
- **(E1 → C6, tests)** Les verrous consultatifs sont communs à toute la base PostgreSQL. Celui de la veille
  (`WATCH_LOCK_SPACE`, identifiant du compte) peut donc se heurter d'un worker de test à l'autre depuis `pytest -n auto`
  (même identifiant de compte dans deux schémas). Jamais vu dans les passages de E1. Parade d'E1 :
  `hashtext(nom || current_schema())` comme première clé.
- **(E1)** Les dates de la liste des messages s'affichent sans l'année (`paris_time`) : suffisant sur la fenêtre de
  30 jours, ambigu au-delà.
- **(E1 → E2, recette de Nicolas du 04/10)** La boîte principale apporte du bruit, comme prévu (E1 ne trie pas) : une
  annonce Tony Dog, une alerte de sécurité GitHub, une publicité france.tv ; des messages trouvés par les deux
  recherches (LinkedIn dans la boîte principale). Cas de test d'E2 : ils ne doivent jamais être rattachés à une
  candidature. L'écran d'E1 dit « Messages non triés » et « Recherche : Boîte principale / Expéditeur d'alertes ».
- **(E1 → §5 VPS)** Client Google en mode « Test » (utilisateurs tests, accès retiré au bout de 7 jours, « Reconnecter »
  en un clic) : le passage en production demande page d'accueil, page de confidentialité et e-mail d'assistance
  (page « Branding »), à faire avec le VPS et la validation de l'application.
- **(E2 → E4)** Les décisions d'E2 ne changent aucune étape. Orientation notée (Q10, à re-décider) : transition sans
  confirmation au seul niveau « haute » et pour refus, entretien, test, offre ; `candidatures.rules.automatic_transition_allowed`
  existe déjà (D1). Une correction de l'utilisateur s'écrit dans `message_decisions` (auteur `user`, jamais écrasée par un
  reclassement) ; les règles par compte nées des corrections complètent les listes du code (`classification/rules.py`).
  Cas connus à corriger par l'utilisateur : InMail de recruteur arrivée par `messages-noreply@linkedin.com`
  (« hors recherche »), newsletter prise pour une alerte par le modèle.
- **(E2 → E3)** Les alertes sont les décisions `job_alert` (adresses `ALERT_SENDERS`, formes d'objet des relais) : E3
  part de ces messages plutôt que de la requête *alertes* d'E1.
- **(E2 → F1)** 🏠 Aujourd'hui « réponses à vérifier » : la vue `View.TO_CHECK` de `MessagesService.state`, et les
  messages en attente (`waiting`, `waiting_reason`).
- **(E2)** Des expéditeurs mettent des entités HTML dans la partie texte (« re&ccedil;u ») : E1 les garde telles quelles,
  la classification les lit décodées (`classification.rules.readable`). À reprendre à la collecte si un autre usage du
  corps en souffre (E3).
- **(E2 → Nicolas)** L'application de développement tourne encore avec l'image d'E1. Relancée
  (`docker compose up -d --build --wait app`), elle classe après chaque collecte et appelle Gemini dans les plafonds du
  compte (20 par heure, 60 par jour).
- **(E2 → plan, Nicolas 05/10)** **E4 passe avant E3** : à la recette d'E2, une vue « À vérifier » sans geste ne sert à
  rien ; les corrections et transitions (E4) d'abord, les alertes comme source (E3) ensuite. E4 reprend aussi le
  rattachement aux candidatures faites hors de Rocky (employeur cité, `employer.cited`, décision E2 Q22) et le
  regroupement des messages d'une même candidature (Q21).
- **(E4 → F1)** 🏠 Aujourd'hui reprend « Ce qui a bougé » : `MessagesService.state(...).moved` et `pending_count` (le
  compteur de 📬 passe par `system.shell.add_badge`, hors bande après un geste).
- **(E4 → F1 ou après, décision E4 Q11)** Passage à « Sans réponse » après un délai sans message : hors E4, par
  `automatic_transition_allowed`, une fois les rattachements fiables (constat D1 → E4, F1).
- **(E4 → Nicolas)** Étiquettes de l'échantillon de l'archive (`tests/messages/data/archive_sample.csv`, colonne `checked`
  vide, recette d'E2) : à reprendre avec les corrections réelles de Nicolas, exportées par
  `rocky-admin messages-etiquettes <email>` (jamais versionnées telles quelles).
- **(E4)** Les décisions d'E2 déjà en base n'ont pas de transition (aucune rétroactivité) : seuls les messages décidés
  depuis E4, ou corrigés et confirmés, font bouger un dossier.
- **(E4)** Après « Créer la candidature », les autres messages qui citent l'employeur sont rattachés par les règles en
  « À vérifier » (nom sans l'intitulé de l'offre, décision E2) : un « Juste » suffit, mais si ces accusés encombrent
  « À regarder », reconnaître aussi l'intitulé saisi à la création.
- **(E4 → D5)** Une transition « Préremplie → Envoyée » tirée d'un accusé (Q2) n'écrit pas de ligne `application_sendings`
  (ni canal ni révision), comme les envois confirmés de D3.
- **(E4 → B1, vérification, à décider avec Nicolas)** 1 409 tests (65 de plus pour E4) : 1 min 30 (1 min 37 au total)
  sur une machine calme, mais 1 min 52 puis **2 min 12** le même jour sous une charge de 12 (autres applications du
  poste, pas Rocky) ; 1 min 10 à E2. La limite des 2 min n'a plus de marge. Leviers : partager le compte et la boîte des
  tests SQL de `messages` (une fixture par module), ou mesurer la limite sur le passage GitHub plutôt que sur le poste.
