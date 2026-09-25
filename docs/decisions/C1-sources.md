# C1 — Sources

Date : 25/09/2026 · Étape : C1 (plan v2) · Préparation : questions à Nicolas puis mode plan

Critère de sortie : « Chaque connecteur testé sur jeux de données enregistrés ; une panne de source est isolée et
visible. »

## Constats de départ (ancien Rocky et archive A1)

| Constat | Source |
|---|---|
| APEC : 659 descriptions incomplètes sur 665 (la recherche ne renvoie qu'un extrait d'environ 280 caractères ; le détail est souvent protégé par DataDome) ; requête sans filtre de lieu (`"lieux": []`) | `job_offers.csv`, `dashboard/rocky/sources/apec.py` |
| 54 veilles sur 54 `PARTIAL` : France Travail `invalid_client` à chaque veille, Indeed/TheirStack à court de quota (26) ou arrêté par une vérification navigateur (11) | `watch_runs.csv` |
| Noms de source hétérogènes : `Apec`, `hellowork.com`, une URL Indeed complète | `job_offers.csv` |
| Contournements : navigateur Playwright qui réutilise la session acceptée par DataDome (détail APEC), repli `curl` quand le CDN de Wellfound refuse la requête | `apec_detail.py`, `wellfound.py` |
| Une exception inattendue d'un connecteur était avalée (`except Exception` sans trace) | `dashboard/rocky/watch.py` |

## Décisions métier (avec Nicolas, 25/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Connecteurs | Portés : **APEC, Adzuna, Welcome to the Jungle, LinkedIn** (liste publique pour visiteurs), **Wellfound**, **France Travail** (« en attente d'accès », D8). **Indeed/TheirStack n'est pas porté** : API payante au quota épuisé ; Indeed arrive par ses alertes e-mail en E3. |
| Q2 | Visibilité d'une panne | Commande de diagnostic `rocky-admin sources` : vraie collecte, résultat affiché source par source. L'état des sources à l'écran (⚙️ Système) reste pour F1. |
| Q3 | Jeux enregistrés | Appels réels autorisés, **une capture par source**, avec les clés lues par l'application (jamais par l'agent). Réponses anonymisées puis versionnées dans `tests/offres/sources/data/`. |
| Q4 | Lieu APEC | Un lieu de piste qu'APEC ne reconnaît pas : la requête est **signalée et sautée** (« lieu non reconnu par APEC : … »). Aucune recherche nationale de repli. |
| Q5 | Ligne rouge de collecte | La ligne rouge porte sur les **protections actives**, pas sur la collecte. *Autorisé* : API officielles ; points d'accès et pages publics consultables sans connexion ; en-têtes de navigateur ordinaires ; volume humain (une page de résultats par requête, pause entre deux requêtes vers un même site). *Interdit* : résoudre ou esquiver un défi anti-robot (DataDome, Cloudflare, CAPTCHA), réutiliser une session ou un compte, proxys et changement d'adresse IP, imitation d'empreinte TLS, réessais. **Règle d'arrêt** : au premier signal de protection (HTTP 403 ou 429, page de défi), la source s'arrête pour la collecte en cours, avec la raison « refusé par la plateforme », sans tenter d'autre moyen. |
| Q6 | Descriptions | Le détail est lu par le point d'accès public de la plateforme quand il existe (APEC `offre/public`, détail WTTJ), sous la règle d'arrêt. Sinon l'offre est **conservée, marquée incomplète avec sa raison**. Compléter depuis la page de l'annonce (LinkedIn, Adzuna) passe par l'import d'URL (C2). La lecture assistée d'une fiche dans un navigateur visible, déclenchée par l'utilisateur, une offre à la fois, est **à trancher en C2 ou C6**. |

Raison de Q5 (échange du 25/09) : collecter les annonces est l'objet de Rocky, et certaines plateformes n'y tiennent
pas. Un en-tête de navigateur n'est pas une protection (le site sert la même page à tout visiteur) ; un défi
anti-robot en est une. Ce qui transforme un usage personnel toléré en collecte gênante, c'est le volume : il est
borné dès maintenant, en prévision du VPS et des alpha-testeurs. Stratégie en couches : API officielles → points
d'accès publics → alertes e-mail (E3, repli quand une source ferme) → import d'URL (C2, geste de l'utilisateur).

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme | Sous-module `rocky/offres/sources/` : `model.py` (codes, offre collectée, ports, erreurs), `rules.py` (pur), `http.py` (client public), un fichier par connecteur, `registry.py`, `usecases.py` | Même forme que les autres modules ; `offres` accueillera ensuite analyse, score et veille. |
| Rien de persisté | Pas de table, de migration ni d'événement en C1 | L'écriture de l'offre, de son rattachement aux pistes et de son score est une unité de C6. |
| Pistes → requêtes | Une requête par couple (intitulé, lieu) des pistes. Mots-clés et mots exclus servent au score (C4). Une source qui ne filtre pas le lieu reçoit une requête par intitulé, et son résultat l'indique | Les intitulés sont des chaînes de recherche (B5, Q25) ; aucune requête inutile. |
| Volume | 20 résultats par requête (valeur de l'ancien Rocky), une seule page ; pause minimale entre deux requêtes vers un même hôte ; aucun réessai | Q5. |
| Faits bruts | Contrat, télétravail et salaire gardés en texte source, plus les bornes numériques quand l'API les donne | Leur interprétation (TJM ≠ salaire, codes de contrat) est l'objet de C3. |
| Noms de source | Codes stockés `apec`, `adzuna`, `wttj`, `linkedin`, `wellfound`, `france_travail` ; libellés à l'affichage. Une URL hors connecteur donne son hôte sans `www` (`hellowork.com`), jamais l'URL entière | Règle B4 (codes anglais, libellés français) ; réutilisé par C2 et E3. |
| Erreurs | `SourceRefused` (protection) distinct de `SourceFailed` (panne) ; les messages ne recopient jamais l'URL ni ses paramètres (clés Adzuna) | Un refus n'appelle pas la même réaction qu'une panne ; aucun secret affiché. |
| Isolation | La collecte donne un résultat par source : `ok`, `refused`, `failed`, `pending_access`, `not_configured`. Une source en attente ou non configurée n'est pas appelée. Une exception inattendue devient `failed` (« erreur technique dans le connecteur ») **et** sa trace est journalisée | Aucune exception avalée ; les autres sources continuent. |
| France Travail | `pending_access` tant que `ROCKY_FRANCE_TRAVAIL_ENABLED` n'est pas `true` ; jeu de test reconstruit (aucune capture possible sans accès) | D8. |
| Dépendances | `httpx2` passe de dev à l'exécution (déjà verrouillé ; `MockTransport` rejoue les jeux enregistrés) ; `beautifulsoup4` pour les pages HTML de LinkedIn et Wellfound (servira à C2). Plus de `requests` | Un seul client HTTP dans le projet. |
