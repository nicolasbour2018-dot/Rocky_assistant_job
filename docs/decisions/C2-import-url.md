# C2 — Import par URL

Date : 25/09/2026 · Étape : C2 (plan v2) · Préparation : questions à Nicolas puis mode plan

Critère de sortie : « Un lien invalide affiche sa raison. »

## Constats de départ (ancien Rocky)

| Constat | Source |
|---|---|
| L'import des liens d'alertes avale toute erreur (`except Exception: continue`) : un lien cassé disparaît sans trace | `dashboard/rocky/gmail_service.py` (`_import_links`) |
| Import manuel : JSON-LD `JobPosting`, puis conteneurs HTML connus, puis texte visible ; complément par Groq | `dashboard/rocky/job_importer.py` |
| Aucune vérification de l'adresse lue : une URL saisie peut viser le réseau interne (SSRF) | `fetch_html` |
| Imports par URL de l'archive : hellowork.com (21), efinancialcareers.fr, cadremploi.fr, free-work.com, sites carrière (Recruitee, Yello, employeurs), Indeed | `job_offers.csv` (A1) |

## Décisions métier (avec Nicolas, 25/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Écriture | **Aperçu seul** : rien n'est persisté en C2 (pas de table `job_offers`). L'offre, son rattachement aux pistes et son score s'écrivent ensemble en C6/C7. |
| Q2 | Affichage | **Formulaire web** « Importer une annonce » dans 🔎 Offres : un lien donne l'aperçu de l'offre ou la raison de l'échec. C7 l'intègre à l'écran complet. |
| Q3 | Page sans annonce structurée | Le **texte visible** de la page devient la description ; l'offre est marquée incomplète (« extraction approximative ») avec sa raison. Rien n'est jeté, tout est signalé. |
| Q4 | Enrichissement (suite de C1, Q6) | C2 livre le **moteur commun** (page ou texte → description d'une offre) et la **description collée**. La lecture assistée (navigateur visible) arrive en C7 avec le geste « Enrichir » : l'application tourne dans Docker, qui ne peut pas ouvrir de fenêtre sur le poste. |
| Q5 | Jeux de test | **Captures réelles**, une page publique par cas, sous la règle d'arrêt de C1 (Q5), anonymisées puis versionnées. |
| Q6 | LLM | **Aucun LLM en C2** : extraction déterministe, un champ absent reste vide. L'extraction par LLM relève de l'analyse d'annonce (C3). |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme | Sous-module `rocky/offres/imports/` : `model.py`, `rules.py` (pur), `usecases.py`, `web.py` ; gabarits `offres/import*.html` | Même forme que `sources/`. |
| Ordre d'extraction | JSON-LD `JobPosting` → conteneurs HTML connus → texte visible. Un bloc JSON-LD illisible est ignoré et signalé | Le JSON-LD (publié pour les moteurs d'emploi) est structuré et stable ; le HTML change à chaque refonte d'un site. |
| Faits bruts | Mêmes règles que C1 : contrat, télétravail et salaire en texte source, bornes numériques et période quand la page les donne ; `validThrough` gardé comme date limite brute (`deadline`) | Interprétation en C3. |
| Nom de source | `CollectedOffer.source` devient un nom de source : code de connecteur, sinon hôte sans `www` (`source_for_url`) | Règle C1 des noms de source, prévue pour C2 et E3. |
| Lecture | `PublicHttp.get_page` : règle d'arrêt de C1, aucun réessai ; redirections suivies une à une (5 au plus) ; page HTML exigée ; 3 Mo au plus | Une seule mécanique de lecture pour sources et import. |
| Adresses internes | Chaque hôte (y compris après redirection) est résolu et doit être public : boucle locale, réseau privé, lien local, adresses réservées refusés | L'URL est choisie par l'utilisateur ; sur le VPS multi-comptes, elle ne doit pas sonder le réseau interne (SSRF). |
| Erreurs | Issue typée : `ok`, `invalid` (lien mal formé ou interdit), `refused` (protection de la plateforme), `failed` (panne, 404, page illisible, pas du HTML). Une exception inattendue devient `failed` (« erreur technique ») **et** sa trace est journalisée | Aucune exception avalée (plan, §6 : `_import_links`). |
| Enrichissement | `enriched(offer, preview)` : description remplacée seulement par une description complète, champs vides complétés, faits présents jamais écrasés, identité conservée | Moteur réutilisé par la lecture assistée (C7) et les alertes (E3). |
| Plateformes sans page lisible | Port `LinkSource` (`from_link` + détail public) : Apec, dont la fiche est une coquille Angular vide. Les autres plateformes (LinkedIn, WTTJ, Hellowork, sites carrière) publient leur `JobPosting` dans la page | Constat des captures du 25/09. |
| Identité | Une page importée est identifiée par son adresse canonique (`external_id` = URL) ; `identifier` du JSON-LD est la référence de l'employeur, pas celle de la plateforme | Déduplication entre import et veille par l'adresse (C6). |
| Lien inconnu | Un nom de domaine qui ne se résout pas est un lien à corriger (`invalid`, sans formulaire de collage) | Trouvé à l'essai : proposer de coller le texte d'un site qui n'existe pas n'a pas de sens. |
| Navigation boostée | `wants_fragment` (HTMX **et** pas `HX-Boosted`) remonte de `profil` vers `system.shell` ; l'import l'utilise | Trouvé à l'essai : le lien « Importer une annonce », boosté par la coque (`hx-boost`), recevait le fragment et la page restait vide. |
| Dépendances | Aucune ajoutée (`httpx2`, `beautifulsoup4` depuis C1) | — |

## Mesures (25/09/2026)

| Contrôle | Résultat |
|---|---|
| Captures réelles (`docs/procedures/c2-captures/`) | Fiches LinkedIn, WTTJ, Recruitee, Hellowork, recherche Hellowork, fiche Apec : **aucun refus**. Pièges révélés : description LinkedIn échappée deux fois ; `estimatedSalary` de Hellowork (estimation de la plateforme, ignorée) ; `jobLocation` en liste, `identifier` numérique ou absent ; fiche Apec vide ; nom d'une recruteuse (LinkedIn) et prénoms de salariés (WTTJ) retirés des jeux |
| **Validation de Nicolas** (25/09) | Deux imports dans l'application : un lien Indeed refusé, erreur claire ; un lien Adzuna importé proprement. C2 validée |
| Vérification globale | `docker compose run --rm --build check` vert : 428 tests en 10 s (16 s au total) ; ruff, mypy strict |
| **Critère de sortie, en réel** (application sur le poste, schéma jetable de `test-db`, Chromium par Playwright) | `pas-une-url` → « Le lien doit commencer par http:// ou https:// » ; `http://127.0.0.1/admin` → « Le lien vise une adresse privée ou locale (127.0.0.1) : Rocky ne lit que des sites publics » ; domaine inexistant → « Le site … est introuvable (nom de domaine inconnu) » ; annonce Hellowork disparue → « L'annonce n'existe plus, ou le lien est faux (HTTP 404) » ; fiche Apec → « Refusé par Apec … (HTTP 403). Tu peux coller la description… » puis collage → aperçu « description collée » ; fiche LinkedIn → aperçu complet (employeur, lieu, contrat, dates, 5 082 caractères). Console sans erreur |
