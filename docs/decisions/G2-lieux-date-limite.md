# G2 — Lieux et date limite

Date : 06/10/2026 · Étape : G2 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q15) puis mode plan

Critère de sortie (plan) : « "Paris 01 - 75", "Courbevoie - 92" et "Chartres - 28" répondent aux lieux des pistes de
Nicolas ; écart de classement chiffré et documenté. »

## Constats de départ

| Constat | Source |
|---|---|
| Le score cherche le lieu de la piste, mot à mot, dans celui de l'annonce ; seule « France » est connue comme zone | `rocky/offres/scoring/rules.py` (`_zone`), `FRANCE_NAMES` |
| Lieux des pistes de Nicolas : « Paris », « Ile de France », « Eure et Loire » (le département s'écrit « Eure-et-Loir ») | `docs/procedures/c5-calibrage/README.md` (profil figé) |
| Mesure du 29/09 : sur 1 304 scores (652 offres × 2 pistes), lieu à 1 dans 156 cas, à 0,3 (hors zone) dans 698 ; 78 offres entre 40 et 49 avec un lieu « hors zone » | plan §8 (C7 → étape à placer) |
| Formes du lieu selon la source : Apec `Paris 01 - 75`, `Courbevoie - 92` ; Indeed `Paris (75)` ; Adzuna `8ème Arrondissement, Paris`, `Val-d'Oise, Ile-de-France` ; LinkedIn, Hellowork la commune seule (`Levallois-Perret`), `Paris et périphérie`, `Ville de Paris` | `job_offers.csv` de l'archive A1 |
| Les lieux des pistes font aussi les requêtes de la veille (Apec les traduit par son autocomplétion, en ligne) | `rocky/offres/sources/rules.py`, `apec.py` |
| Date limite sans année lue avec l'année du jour d'affichage (`today`) : « avant le 15 janvier » lu le 20/12 tombe dans le passé | `rocky/offres/analysis/rules.py` (`_deadline`), revue H |
| Date limite affichée seulement dans la fiche (badge ⏰) | `rocky/offres/templates/offres/offer_body.html` |
| Hellowork : le JSON-LD donne `FULL_TIME`, le CDI n'est que dans le titre de la page | plan §8 (C3 → C2, C6) |
| Date de publication présente pour 1 271 annonces sur 1 276 de l'archive | `job_offers.csv` |
| Une nouvelle `RULES_VERSION` (score ou analyse) change `inputs_hash` : tous les scores sont recalculés par la tâche existante | `rocky/offres/rules.py` (`inputs_hash`) |

## Décisions métier (grill avec Nicolas, 06/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Référentiel | **Code officiel géographique INSEE 2026** (communes, arrondissements municipaux, départements, régions ; licence ouverte), réduit à code, nom, département, région et versionné dans le dépôt, millésime dans le nom du fichier. Lu sans réseau, avec `csv` de la bibliothèque standard ; pas de population. |
| Q2 | Ce que nomme un lieu de piste | Une commune, un département (nom ou numéro), une région, la France. Une commune ne couvre qu'elle-même et ses arrondissements (« Paris » couvre « Paris 08 - 75 »). **Pas de rayon** autour d'une commune : on nomme le département ou la région. |
| Q3 | Lieu de piste non reconnu | Comparé mot à mot comme avant, avec un avertissement visible. Pas de correction approximative (« Loire » répondrait au département de la Loire). Nicolas corrige « Eure et Loire » en « Eure-et-Loir ». |
| Q4 | Lieu d'une annonce | Dans l'ordre : numéro de département écrit (`- 92`, `(95)`) ; chaîne entière comme commune, puis chaque morceau séparé par une virgule ; nom de département ou de région dans la chaîne ; à défaut, comparaison mot à mot. Un homonyme sans département est dans la zone si **l'une** des communes de ce nom l'est ; le détail le dit. |
| Q5 | Valeurs | Inchangées : dans la zone 1, hors zone 0,3, hybride hors zone inchangé. Seule la définition de « dans la zone » change. |
| Q6 | Veille | Requêtes inchangées : le référentiel ne sert qu'au score. |
| Q7 | Date limite passée | **Signalée** : badge dans la liste, la carte du mode tri et la fiche. Ni écart automatique ni effet sur le score (indicateur calculé, plan §3). Le motif « date limite dépassée » d'abord prévu est **retiré** (Q16). |
| Q8 | Date sans année | Référence = **date de publication** : l'année suivante si la date tombe avant la publication. Nouvelle `RULES_VERSION` de l'analyse. Raison (exemple du grill corrigé à l'implémentation) : publiée le 10/12 avec « avant le 15 janvier » et relue le 20/01, la référence du jour d'affichage donnerait janvier de l'année d'après, jamais « passée » ; la date de publication donne le 15/01, passée. |
| Q9 | Contrat dans le titre | Pour **toute** page importée (URL, liens des alertes E3) dont le JSON-LD ne donne qu'un code générique (`FULL_TIME`, `PART_TIME`) alors que le `<title>` nomme un contrat français (CDI, CDD, stage, alternance, intérim, freelance). Les offres déjà enregistrées ne sont pas relues. |
| Q10 | Mesures | Avant et après : C5 (50 annonces annotées), C4 (404 annonces de l'archive), comptage du 29/09 sur la base de développement. |
| Q11 | Place du référentiel | Module **`profil`** (`rocky/profil/places.py` et ses données) : il dit ce que couvre un lieu de piste. `offres` l'importe, dans le sens actuel des dépendances (offres → profil). |
| Q12 | Fabrication | Script `docs/procedures/g2-lieux/` : téléchargement unique du COG (réseau, avec l'accord de Nicolas), réduction, écriture du fichier versionné. Alias écrits à la main : « IDF », « Ville de Paris », « Paris et périphérie » → Paris, Hauts-de-Seine, Seine-Saint-Denis, Val-de-Marne ; « Paris La Défense » → Hauts-de-Seine ; anciens noms de régions (« Centre »…). |
| Q13 | Sans date de publication | Référence = jour de l'affichage (`today`), sans faire passer la première collecte jusqu'à l'analyse (0,4 % des annonces). |
| Q14 | Mode tri | L'offre à date limite passée reste dans la file « à examiner », avec son badge ; pas de nouveau filtre (le cockpit G3 pourra s'en servir). |
| Q15 | Lieu de piste non reconnu, où | Dans l'édition de la piste **et** dans le « Pourquoi ? » de la composante lieu. |
| Q16 | Motif « date limite dépassée » (posée à l'implémentation) | « Écarté » a déjà 9 motifs, le maximum des touches 1–9 (règle C7). **Pas de nouveau motif** (Nicolas) : le badge suffit ; une date dépassée s'écarte avec « autre » et une précision, comme le 29/09. |

## Décisions techniques (implémentation)

| Sujet | Décision | Raison |
|---|---|---|
| Fichier | `rocky/profil/data/lieux-cog-2026.csv` (1,2 Mo) : type, code, nom, commune (celle d'un arrondissement), département, région ; procédure `docs/procedures/g2-lieux/` | Seul ce que lit le score ; un arrondissement se lit comme sa commune (« Paris 1er Arrondissement » → Paris). |
| Lecture | `rocky/profil/places.py`, fonctions pures, fichier chargé une fois (`functools.cache`) ; noms comparés par `normalize_term`, « St » = « Saint » | Même forme de comparaison que les compétences ; aucune correction approximative (Q3). |
| Nom de plusieurs sortes | Le plus large l'emporte (région, puis département, puis commune) : « Paris » est le département 75, « Bretagne » la région | Comme Apec (`apec.py`, le lieu le plus large). |
| Numéro de département | Il départage le nom écrit à côté (« Montreuil - 93 », « Paris 08 - 75 » → la commune de Paris) ; seul, il donne le département. Un code postal (« 91100 ») vaut son département, sauf la Corse (« 20… », deux départements). | Une piste nommée par une commune répond à « Paris 08 - 75 ». |
| Commune seule dans son département | Elle couvre aussi ce département (Paris, 75) ; règle déduite du fichier | « Paris (75) » lu comme le département répond à une piste « Paris ». |
| Alias | Ceux de Q12, plus « petite couronne », « région parisienne », les régions d'avant 2016 et « Saint-Ouen » → Saint-Ouen-sur-Seine (renommée en 2018, 6 scores hors zone à tort dans la mesure). Un alias cède devant un numéro de département qui le contredit (« Saint-Ouen - 41 »). | Noms que les annonces écrivent et que le COG ne connaît plus ou pas. |
| Étranger | Une annonce dont le pays est connu et étranger n'est jamais lue dans le référentiel : seulement la comparaison mot à mot (C5, Q24) | « Paris, US » ne tombe pas en Île-de-France. Une annonce **présumée** à l'étranger (Wellfound sans pays) l'est : « Paris » y lève le plafond, comme le faisait le lieu « Paris » des pistes avant le 29/09. |
| Télétravail comme lieu | « Télétravail complet » (suggéré par l'aide du formulaire) n'est pas signalé comme lieu non reconnu | Ce n'est pas un lieu ; l'avertissement serait du bruit. |
| Détail du score | « Courbevoie - 92 : Courbevoie (Hauts-de-Seine), dans la zone « Ile de France » » ; hors zone : « Le Mans : Le Mans (Sarthe) : hors des lieux de la piste (…) » ; homonyme : « une commune de ce nom, … » | Chaque score s'explique (C4). |
| Caractéristiques (D14) | `place_departements` (départements lus, plusieurs pour un homonyme) et `deadline` (date limite lue par l'analyse) | La liste lit la date limite dans le score courant, sans relancer l'analyse de chaque offre (C7 : la liste ne lit que les scores) ; recalculée à chaque changement de version. |
| Contrat dans le titre | Retenu aussi quand le JSON-LD ne donne **aucun** contrat (extension de Q9) ; mots cherchés en mots entiers (« Cdiscount » n'est pas un CDI) | Le titre est alors le seul fait disponible. |
| Versions | `score-2026-10-06.1`, `analyse-2026-10-06.1` | Les deux entrent dans `inputs_hash` : tous les scores sont recalculés par la tâche existante. |

## Dépendances

Aucune.

## Mesures (06/10/2026)

Avant : `score-2026-09-29.3` ; après : `score-2026-10-06.1`. Pistes du jour, inchangées pendant G2 : « Ile de France »,
« Eure et Loir » (déjà écrit sans la coquille « Loire » : reconnu, aucune correction de piste nécessaire, requête Apec
inchangée). « Paris » a été retiré des pistes après le 29/09 : le point de départ est remesuré avec ces pistes et diffère
de la mesure C5 du 29/09 (AUC 0,94 ce jour-là, 0,93 aujourd'hui avant G2), Paris étant alors hors zone.

**Base de développement** (`docs/procedures/g2-lieux/`, 1 663 offres, 3 326 scores) :

| | Avant | Après |
|---|---|---|
| Composante lieu à 1 (dans la zone) | 318 | 2 778 |
| Composante lieu à 0,3 (hors zone) | 2 290 | 220 |
| Offres au-dessus du seuil | 211 | 324 |
| Offres entre 40 et 49 avec un lieu hors zone | 225 | 24 |

Corrélation de rang avant / après 0,96 ; 113 offres passent au-dessus du seuil, aucune ne passe dessous ; 14 des 15
premières restent en tête. Hors zone restants : Le Mans, Orléans, Nantes, Lyon, « France » sans ville, l'étranger.

**Calibrage C5** (50 annonces annotées, `docs/procedures/c5-calibrage/`) :

| | `score-2026-09-29.3` | `score-2026-10-06.1` |
|---|---|---|
| AUC pertinente / Non | 0,93 | 0,94 |
| Pertinentes / Non dans les 10 premières | 9 / 1 | 9 / 1 |
| Seuil 50 : Oui, pertinentes, Non au-dessus | 12/12, 20/21, 5/29 | 12/12, 20/21, 5/29 |
| Contrôle (30 candidatures) : rang médian, premier quart, au-dessus du seuil | 28 %, 14, 27 | 27 %, 13, 28 |

**Mesure C4** (404 annonces de l'archive) : C4 ≥ 50 179 → 187 ; moyenne 48,2 → 50,7 ; la « Data Protection
Analyst » (1193) 38 → 45, toujours sous le seuil (critère de C4 tenu).

Lecture : les lieux corrigés relèvent les annonces d'Île-de-France et d'Eure-et-Loir de 7 à 10 points sans déranger
l'ordre des annotations : dans C5, le lieu est un motif + pour les 21 pertinentes comme pour 17 Non sur 29, qui montent
donc ensemble. L'effet se voit sur la base réelle, où « Paris » seul comptait 590 scores hors zone.

## Clôture (06/10)

Critère vérifié sur la base de développement, scores **enregistrés** recalculés par l'application
(`score-2026-10-06.1`, 3 326 scores) : « Paris 01 - 75 », « Courbevoie - 92 » et « Chartres - 28 » valent 1 au lieu pour
les deux pistes (« … : Courbevoie (Hauts-de-Seine), dans la zone « Ile de France » »). Écart de classement chiffré
ci-dessus et dans `docs/procedures/g2-lieux/README.md`. Vérification globale verte (1 614 tests en 52 s), puis de nouveau
après la fusion de H1.
