---
title: Rocky Job Assistant
emoji: 🔎
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8501
pinned: false
short_description: Assistant personnel et explicable de recherche d'emploi
---

# Rocky Assistant

Rocky est une base pédagogique en Python pour centraliser une recherche
d'emploi. Il importe une annonce depuis son URL, calcule un score explicable,
prépare une lettre de motivation contrôlée et organise une veille quotidienne.

Rocky ne valide jamais une candidature à ta place. Il prépare le CV et la
lettre, conserve le suivi puis ouvre le formulaire officiel.

## 1. Installation

Depuis ce dossier :

    python3.13 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt

Le projet utilise volontairement l'environnement virtuel. Sur ce Mac, la
commande système python3 pointe vers Python 3.9, trop ancien pour l'ancien code.

## 2. Configuration

Le fichier .env local est ignoré par Git. Renseigne les groupes de valeurs
suivants sans ajouter de guillemets :

- PostgreSQL : DB_USER, DB_PASSWORD, DB_HOST, DB_PORT et DB_NAME ;
- Mistral : MISTRAL_API_KEY ;
- France Travail : FRANCE_TRAVAIL_CLIENT_ID et
  FRANCE_TRAVAIL_CLIENT_SECRET ;
- Adzuna : ADZUNA_APP_ID et ADZUNA_APP_KEY ;
- veille : MATCH_THRESHOLD, égal à 70 par défaut.

`DATABASE_URL` est facultatif en local : PostgreSQL reste alors construit avec
les cinq variables `DB_*`. Dans le Space Hugging Face, Rocky utilise une base
SQLite montée dans `/data`, ce qui évite d'héberger un serveur PostgreSQL dans
le même conteneur.

Le modèle est mistral-small-latest. Rocky utilise le mode JSON du SDK pour
valider les champs extraits au lieu d'interpréter du texte libre.

Le connecteur France Travail utilise exclusivement l'API officielle Offres
d'emploi v2 (`/partenaire/offresdemploi/v2/offres/search`). Son accès est
ouvert, mais nécessite tout de même de créer une application sur
`francetravail.io`, de demander l'accès au produit « Offres d'emploi », puis de
copier le `client_id` et le `client_secret` applicatifs dans `.env`. Les
identifiants du compte candidat France Travail ne fonctionnent pas pour OAuth.

Crée d'abord une base PostgreSQL vide, puis initialise ses tables :

    python scripts/init_db.py
    python scripts/bootstrap_profile.py

Le schéma database/schema.sql est idempotent : tu peux relancer cette commande
après une évolution sans effacer les annonces existantes.

## 3. Lancer le dashboard

Le point d'entrée unique de Rocky V2 est `dashboard/dashboard_v2.py` :

    python -m streamlit run dashboard/dashboard_v2.py

Pour un déploiement local détaché, limité à ce Mac :

    .venv/bin/python scripts/start_local.py

Le dashboard reste alors disponible sur `http://127.0.0.1:8501`. Son PID et
ses logs sont conservés dans `logs/`, sans installer de service système.

Ordre conseillé :

1. créer ou sélectionner un profil ;
2. définir ses postes, lieux, contrats et compétences ;
3. rendre ce profil actif pour la veille ;
4. téléverser son CV PDF ;
5. importer une première annonce par URL.

Certaines pages LinkedIn, Indeed ou Welcome to the Jungle bloquent les lectures
automatiques. Rocky affiche alors une erreur claire et le formulaire reste
disponible pour coller le texte manuellement.

## 4. Comprendre le matching

Le score n'est pas décidé par le LLM. Il est calculé dans
dashboard/rocky/matching.py avec les poids initiaux suivants :

- compétences : 55 % ;
- intitulé : 20 % ;
- contrat : 8 % ;
- localisation : 8 % ;
- télétravail : 5 % ;
- salaire : 4 %.

Un critère réellement absent de l'annonce ou du profil est retiré du
dénominateur. Les autres poids sont alors renormalisés. Le détail enregistré
dans job_matches.breakdown explique chaque point du score.

Pour changer le barème, modifie uniquement WEIGHTS, puis lance les tests.

## 5. Lettre et dossier de candidature

Le corps fixe est dans templates/lettre_motivation.txt. Les seules variables
autorisées sont le poste, l'entreprise, l'adresse, la date, le destinataire et
le paragraphe entreprise. Le dashboard impose une prévisualisation et une case
de validation avant de créer :

- une copie du CV associé au profil ;
- une lettre DOCX éditable ;
- une lettre PDF prête à envoyer.

Les dossiers privés sont créés dans output/candidatures/ et ignorés par Git.

## 6. Veille du matin

Teste toujours la commande manuellement avant cron :

    .venv/bin/python scripts/run_watch.py

Le dashboard et le script utilisent le même registre de sources. Le script :

1. lit le profil marqué actif ;
2. interroge France Travail, Adzuna, LinkedIn, Indeed, Welcome to the Jungle,
   Apec et Wellfound ;
3. normalise et déduplique les annonces ;
4. calcule leur matching ;
5. insère seulement celles ayant au moins 70 % ;
6. isole la panne d'une plateforme et continue avec les autres ;
7. écrit le détail par source dans watch_runs et logs/veille.log.

Indeed est collecté via l'API Job Search de TheirStack, sans scraper Indeed.
`THEIRSTACK_API_KEY` sert à la fois à cette collecte et au réenrichissement
volontaire. Rocky filtre `indeed.com`, les intitulés et préférences du profil,
les offres ouvertes et leur fraîcheur. Une seule page plafonnée par
`WATCH_RESULTS_PER_QUERY` est demandée afin de maîtriser les crédits.

Dans `job_offers`, `source_name = Indeed` conserve la source fonctionnelle et
`collector_name = TheirStack` conserve le collecteur technique. Le champ
`description_enrichment_source` reste réservé à l'enrichissement d'une annonce
déjà connue. Les autres plateformes publiques peuvent temporairement refuser
une requête automatisée ; Rocky l'indique alors dans le bilan `PARTIAL` sans
contourner CAPTCHA, connexion ou protection anti-robot.

Le fichier cron/rocky.cron.example contient la ligne prévue pour 07 h 30.
Ouvre crontab -e, colle uniquement la ligne non commentée, enregistre puis
vérifie avec crontab -l. Cette étape écrit dans la configuration système :
elle reste donc volontairement manuelle.

Sur Hugging Face, un planificateur interne exécute aussi la veille à 07 h 30,
heure de Paris. Si le Space dormait à cette heure, Rocky rattrape la veille dès
son prochain démarrage. Le bouton « Lancer la veille maintenant » reste
disponible dans le dashboard.

## 7. Déploiement Hugging Face

Le Space utilise le `Dockerfile` fourni et doit rester privé, car il contient
le CV et des données de candidatures. Les secrets Mistral, France Travail et
Adzuna sont configurés dans les secrets du Space, jamais copiés dans l'image.

Les données modifiables sont séparées du code :

    /app    code du Space, en lecture
    /data   base SQLite, CV et dossiers de candidature

Le volume Hugging Face `rocky-data` est monté sur `/data`. Si aucun volume
n'est attaché, l'application fonctionne mais les données peuvent disparaître
lors d'un redémarrage du Space.

Après activation d'un plan Hugging Face autorisant Docker, la bascule finale
et le montage du volume se font sans suppression de fichier :

    python scripts/activate_hf.py

## 8. Organisation du code

    dashboard/dashboard_v2.py         point d'entrée unique Streamlit V2
    dashboard/dashboard_b.py          cockpit et cartes d'annonces
    dashboard/dashboard_common.py     composants partagés du dashboard
    dashboard/page_*.py               pages secondaires de Rocky V2
    dashboard/job_analysis.py         dictionnaire de compétences existant
    dashboard/rocky/config.py         lecture unique du .env
    dashboard/rocky/database.py       connexion et schéma
    dashboard/rocky/repository.py     toutes les requêtes SQL
    dashboard/rocky/job_importer.py   lecture URL, JSON-LD et HTML
    dashboard/rocky/matching.py       score déterministe
    dashboard/rocky/llm.py            seul accès à Mistral
    dashboard/rocky/letters.py        prévisualisation, DOCX et PDF
    dashboard/rocky/sources/          connecteurs de veille indépendants
    dashboard/rocky/sources/apec_detail.py extraction exhaustive des fiches Apec
    scripts/extract_apec_offer.py     export JSON Apec avec navigateur visible
    dashboard/rocky/watch.py          orchestration quotidienne
    database/schema_sqlite.sql        schéma du Space Hugging Face
    Dockerfile                        image Streamlit du Space

Pour ajouter une source, crée une classe avec un nom et une méthode `search`
qui renvoie une liste de `JobOffer`, puis ajoute-la uniquement dans
`dashboard/rocky/sources/registry.py`.

### Extraction détaillée d’une offre Apec

Le script Playwright dédié ouvre par défaut un navigateur visible, charge la
fiche Angular, puis exporte les champs normalisés, les trois descriptions
(poste, profil et entreprise), toutes les compétences, le profil entreprise,
le composant DOM ciblé et les réponses JSON brutes :

```bash
.venv/bin/python scripts/extract_apec_offer.py \
  "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/179302541W"
```

Le résultat est écrit dans `output/apec/<numero-offre>.json`. L’option
`--headless` est disponible pour une future automatisation ; le script
n’enregistre rien dans la base et ne clique jamais sur « Postuler ».

## 9. Débogage

Lance les contrôles hors réseau :

    python -m pytest
    python -m compileall dashboard scripts

Puis vérifie le dashboard avec la base réelle, sans lancer de serveur :

    python scripts/smoke_dashboard.py

En cas de problème :

- configuration : ouvre l'onglet Diagnostic sans copier de secret ;
- PostgreSQL : relance python scripts/init_db.py ;
- import URL : regarde le message puis essaie le collage manuel ;
- veille : consulte logs/veille.log et la table watch_runs ;
- Mistral : vérifie seulement que la clé est signalée Configuré ;
- documents : vérifie que le CV du profil est un PDF et que
  output/candidatures/ est accessible en écriture.

Pour tester les connexions sans afficher les clés :

    python scripts/check_connections.py

Pour n'appeler qu'un service pendant un diagnostic :

    python scripts/check_connections.py --only france-travail

Les identifiants acceptés incluent aussi `linkedin`, `indeed`,
`welcome-to-the-jungle`, `apec` et `wellfound`.

Les appels Mistral et API sont isolés, ce qui permet de les simuler dans les
tests sans dépenser de crédits.
