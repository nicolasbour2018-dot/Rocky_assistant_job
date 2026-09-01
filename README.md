# Rocky

Rocky est un assistant local et explicable de recherche d'emploi. Il collecte
des offres publiques, calcule un matching déterministe, prépare des documents
bilingues et trie les réponses Gmail en lecture seule. Il ne soumet jamais une
candidature et ne clique jamais sur « Postuler ».

## Pré-requis

- macOS, Python 3.11 ou plus récent et PostgreSQL local ;
- un environnement virtuel dans `.venv` ;
- Chromium Playwright installé (`.venv/bin/python -m playwright install chromium`) ;
- LibreOffice installé pour convertir les lettres DOCX en PDF.

Le dépôt est prévu pour une exécution native macOS. `compose.yaml` reste un
prototype local non suivi dans les commits fonctionnels ; aucun déploiement
Hugging Face n'est prévu par cette version.

## Installation et configuration

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp .env.example .env
```

`dashboard/rocky/config.py` est l'unique lecteur de `.env`. Renseigne dans
`.env` les identifiants PostgreSQL, les clés API utilisées et, si nécessaire,
les réglages SMTP. Les adresses Gmail réelles vont uniquement dans
`GMAIL_ACCOUNTS`, jamais dans le dépôt ; les jetons sont dans
`data/users/<user_id>/gmail/accounts/`.

La base PostgreSQL configurée est la source de données courante. Une base vide
est créée avec `database/schema.sql` ou `database/schema_sqlite.sql`. Une base
existante est seulement validée : si son schéma est incompatible, Rocky échoue
avec une erreur explicite. Il n'y a pas de migration automatique ni de reprise
silencieuse d'un ancien format.

## Lancer Rocky

```bash
.venv/bin/python -m streamlit run dashboard/dashboard_v2.py
```

Crée un compte, active-le via le lien SMTP, puis importe un CV PDF et une lettre
DOCX dans Profil & CV. Les versions françaises et anglaises sont séparées ;
Rocky ne traduit que les champs courts validés et ne fabrique aucune expérience.

## Documents et candidature

Le CV français peut être ciblé avec les compétences et projets déjà présents
dans le profil. PyMuPDF est utilisé exclusivement par `cv_tailoring.py` pour
réécrire les zones autorisées du modèle ; il n'entre pas dans les scores ATS.
Les deux PDF générés sont stockés sous `data/users/<user_id>/output/candidatures/`.

Quand les deux PDF sont validés, le bouton **Préremplir avec Playwright** ouvre
Chromium avec une session privée au compte, renseigne les champs reconnus et
laisse l'utilisateur relire puis envoyer lui-même le dossier. Aucun bouton de
soumission n'est ciblé.

## Gmail et veille quotidienne

Gmail demande uniquement le scope `gmail.readonly`. Chaque adresse possède un
jeton distinct et les décisions automatiques restent limitées aux signaux à
haute confiance ; les cas ambigus restent dans la file de revue.

Pour une exécution manuelle :

```bash
.venv/bin/python scripts/run_daily.py --dry-run
.venv/bin/python scripts/run_daily.py
```

Le scheduler intégré et l'exemple `cron/rocky.cron.example` déclenchent Gmail
puis la veille à **12:00 Europe/Paris**. Le cron n'est jamais installé
automatiquement.

## Vérifications

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall dashboard scripts
.venv/bin/python scripts/smoke_dashboard.py
```

Les tests sont hors ligne : les APIs et le client Mistral sont simulés. Le
smoke dashboard lit la base locale mais n'envoie aucun message et ne lance
aucune candidature.

## Structure

- `dashboard/dashboard_v2.py` : point d'entrée Streamlit ;
- `dashboard/rocky/` : configuration, repository SQL et services métier ;
- `database/` : schémas complets pour une base vide ;
- `assets/` : modèle CV et polices ;
- `.agents/skills/playwright-cli/` et `.claude/skills/playwright-cli/` :
  instructions Playwright versionnées avec le projet.
