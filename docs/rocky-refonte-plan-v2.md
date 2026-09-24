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
(préremplissage) · LLM (Groq, délais d'attente, sorties structurées validées).

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
| B3. Comptes et sessions | Comptes, SMTP ; sessions D11 ; tout le SQL d'authentification dans l'accès SQL de `system` | Rechargement, URL directe et redémarrage du navigateur gardent la session ; la déconnexion l'invalide | ⬜ |
| B4. Coque web et prototype | FastAPI + Jinja + HTMX ; layout et 7 entrées de navigation ; prototype de l'écran de tri sur données factices | Décision explicite : HTMX confirmé ou plan B (NiceGUI) | ⬜ |
| B5. Profil et pistes | Profil unique FR/EN ; compétences avec alias canoniques (ex. « NLP » = « Traitement du langage naturel (NLP) ») ; pistes (intitulés, mots-clés, lieux) ; réimport du profil de Nicolas depuis l'archive ; édition séparée de l'onboarding ; projets affichés proprement ; activation sans kit anglais | Profil réimporté sans doublons ; au moins 2 pistes définies | ⬜ |

### C. Offres

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| C1. Sources | Contrat `JobSource` et registre repris ; connecteurs portés un à un ; APEC avec filtre de lieu et gestion honnête des descriptions incomplètes ; France Travail « en attente d'accès » (D8) ; noms de source normalisés | Chaque connecteur testé sur jeux de données enregistrés ; une panne de source est isolée et visible | ⬜ |
| C2. Import par URL | JSON-LD puis HTML ; erreurs remontées avec leur raison (plus d'exception silencieuse) | Un lien invalide affiche sa raison | ⬜ |
| C3. Analyse d'annonce | `job_analysis` rapatrié dans `offres` ; compétences via les alias ; critères éliminatoires distincts des préférences ; date limite ; TJM distinct du salaire annuel ; description mise en forme ; résumé de description | Extraction mesurée sur un échantillon de l'archive | ⬜ |
| C4. Scoring : règles | Fonction pure sans effet de bord (ne modifie ni l'offre ni la base) ; **preuve minimale** (pas de composante compétences pleine sur 1–2 compétences) ; **indice de confiance** affiché ; intitulé comparé aux intitulés des pistes ; détail et preuves par composante ; version des règles ; caractéristiques stockées (D14) | Chaque score s'explique composante par composante ; la « Data Protection Analyst » (79,6 % en v1) ne remonte plus | ⬜ |
| C5. Scoring : calibrage | Nicolas annote 40–50 annonces de l'archive (pertinente / non, avec motif) ; comparaison des classements ancien vs nouveau ; ajustement des règles | Les annonces jugées pertinentes remontent ; écart chiffré et documenté | ⬜ |
| C6. Veille | Veille par pistes ; **toutes** les offres conservées, sous le seuil avec leur motif ; offre + rattachement aux pistes + score écrits comme une unité cohérente et idempotente ; veille toujours close (terminée / partielle / échouée / interrompue) ; source en attente ≠ échec ; planificateur unique et rattrapage (D12) | Une panne simulée laisse un statut final explicite et aucune offre orpheline ou sans score | ⬜ |
| C7. Écran Offres | Décisions (valeur, raison, auteur) ; mode tri une offre à la fois au clavier ; liste compacte filtrable (piste, sous le seuil, incomplètes) ; fiche latérale avec synthèse de décision (date limite, éliminatoires, preuves du profil, manques) et « Pourquoi ? » ; retour « pertinente / non pertinente » avec motif (étiquettes D14) | Tri de 20 offres au clavier ; chaque décision est tracée dans `events` | ⬜ |

### D. Candidatures

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| D1. Dossier et statuts | Étapes (préparée, préremplie, envoyée, suivie…) ; transitions et **annulation dans une seule transaction** ; prochaine action datée, différable | Une panne injectée pendant l'annulation ne laisse aucun état contradictoire | ⬜ |
| D2. CV maître et rendu | CV structuré FR/EN ; gabarit HTML/CSS → PDF (Playwright) ; listes déterministes ; fin du verrou Canva (SHA-256, coordonnées pixels) et de LibreOffice ; « Vérifier mon CV » (ATS V3 porté) | CV FR et EN validés visuellement par Nicolas ; parsing du PDF vérifié | ⬜ |
| D3. Ciblage et traduction | Sélection et ordre des éléments selon l'annonce ; traduction champ par champ avec glossaire et validation | CV anglais ciblé sans ressaisie | ⬜ |
| D4. Lettre et message | Même moteur ; storytelling de préparation ; ton des prompts revu (pas de jugement dévalorisant sur la reconversion) | Lettres FR et EN validées sur 3 annonces réelles | ⬜ |
| D5. Révisions et envoi | Chaque génération dans un chemin immuable avec hash, vérifié au téléchargement ; préremplissage navigateur porté (confirmation avant) ; confirmation d'envoi au retour avec date et canal | Deux générations → deux PDF distincts récupérables ; l'envoi est lié à la révision exacte | ⬜ |
| D6. Écran Candidatures | Kanban ou liste dense avec filtres par étape ; dossier en 4 étapes (CV → lettre → envoi → suivi) ; chronologie, notes | Une relance due est retrouvée en moins de 3 clics | ⬜ |

### E. Messages

| Étape | Contenu | Critère de sortie | État |
|---|---|---|---|
| E1. Collecte | Gmail lecture seule, plusieurs boîtes ; requête filtrée (`-category:promotions -category:social`…) ; message **enregistré avant toute décision**, de façon idempotente | Une resynchronisation ne retraite rien ; aucun statut ne change sans message enregistré | ⬜ |
| E2. Classification | 3 étages : expéditeur → domaine exact de l'employeur (plus de sous-chaîne) → LLM pour l'ambigu ; confiance réelle (plus de valeurs constantes) ; preuve : règle, extrait, auteur | 100 % des décisions ont une preuve lisible ; le digest Quora n'est plus rattaché à « French bee » ; jeu de test issu de l'archive | ⬜ |
| E3. Alertes comme source | Mails d'alerte Indeed, APEC, LinkedIn, WTTJ, Hellowork, Cadremploi → offres via le module `offres` ; erreurs d'import visibles | Au moins une offre Indeed réelle par jour | ⬜ |
| E4. Décisions et écran | Transition de candidature appliquée dans la même transaction que la décision ; « ce qui a bougé depuis ta dernière visite » ; correction humaine → nouvelle règle ; corrections conservées comme jeu étiqueté | Aucun changement de statut ne passe inaperçu | ⬜ |

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
- **(B2 → D6, F1)** Aucune lecture du journal n'existe encore : la chronologie par sujet (`ix_events_subject`)
  s'écrit avec le premier écran qui l'affiche.
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
