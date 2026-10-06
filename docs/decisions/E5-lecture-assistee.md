# E5 — Lecture assistée

Date : 05/10/2026 · Étape : E5 (plan v2, après E3) · Préparation : mode plan, questions à Nicolas (Q1–Q6)

Critère de sortie (plan) : « Une offre Apec incomplète enrichie depuis sa fiche ».

## Constats de départ

| Constat | Source |
|---|---|
| Deux voies d'enrichissement coexistantes, tranchées par Nicolas le 25/09 : **lecture assistée** (navigateur visible, sur son geste, une offre à la fois, jamais dans la veille) et **description collée** | décision C1, Q6 ; plan §8 (C1 → C2, C7) |
| La description collée est livrée (`with_pasted_description`, `enrich_offer`, touche `c` de la fiche) ; la lecture assistée a été reportée en C7 (pas de Playwright), puis hors de D2 (autre logique métier) | décisions C7 (Q5), D2 (Q3, Q28) |
| Moteur commun déjà là : `parse_page` (JSON-LD → conteneur connu → texte visible marqué incomplet), `enriched` (description remplacée seulement par une complète, faits connus jamais écrasés, identité gardée) | `rocky/offres/imports/rules.py`, décision C2 |
| Le **poste Rocky** (D5) ouvre un Chromium visible au profil persistant sur l'ordinateur, joint par l'application dans Docker (`host.docker.internal:8765`), gardé (loopback, `Host`, pas d'`Origin`, JSON) ; en sommeil depuis l'échec du préremplissage. Il est l'adaptateur prévu de la lecture assistée | décision D5 (Q1, recette du 04/10) ; plan §8 (D5 → E5) |
| La page d'une annonce Apec est une **coquille Angular** : lue par un simple client HTTP, elle ne contient pas l'annonce. `parse_page` n'a aucun conteneur Apec ; le texte visible serait refusé par `enriched` | `docs/procedures/c2-captures/README.md` ; `rocky/offres/sources/apec.py` |
| Une offre d'alerte non lue garde le lien de suivi de la carte (`emails.hellowork.com/clic…`), qui mène au site de la plateforme ; sa source est le nom du site (`hellowork.com`) | `rocky/messages/alerts/rules.py` (`card_offer`), décision E3 |
| Ligne rouge : jamais de résolution ni d'esquive d'un défi anti-robot, jamais d'imitation d'empreinte, aucun réessai | décision C1, Q5 |

## Décisions métier (Nicolas, 05/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Geste | **Deux temps** : « Ouvrir dans le navigateur » (le poste ouvre un onglet) ; l'utilisateur passe l'éventuel défi, puis clique « Lire la page affichée » dans Rocky. C'est l'utilisateur qui dit quand la page est prête : cela vaut pour tout site. |
| Q2 | Offres | **Toute offre incomplète**, quelle que soit sa source (Apec, LinkedIn, Adzuna, fiches d'alertes non lues). Le profil persistant du poste garde les connexions de l'utilisateur. Le critère de sortie se vérifie sur Apec. |
| Q3 | Texte visible | Seule une description **reconnue** (JSON-LD, conteneur connu, lecteur Apec) complète l'offre. Un simple texte visible (menus et mentions compris) ne remplace pas la description : Rocky affiche la raison (« colle la description »). Les faits manquants trouvés sur la page sont complétés quand même (`enriched`). |
| Q4 | Essai réel | Accordé en début d'étape : 1 ou 2 fiches Apec, ouvertes par Nicolas avec le poste ; la page rendue est sauvegardée hors du dépôt, puis anonymisée pour les tests. **Au premier blocage, on s'arrête et on en parle.** |
| Q5 | Onglet | **Laissé ouvert** après la lecture (comme en D5) : c'est le navigateur de l'utilisateur. |
| Q6 | Autre page | **Refus avec sa raison** si le site affiché n'est pas celui de l'offre (navigation ailleurs, redirection vers une connexion d'un autre domaine) : « la page affichée n'est plus l'annonce ». |

### Après le blocage de la recette (Nicolas, 05/10)

Constat : au second essai réel, Apec refuse le navigateur piloté du poste (« Access is temporarily restricted »,
« Automated (bot) activity »), sans défi à passer. Le passer demanderait de maquiller le navigateur : ligne rouge C1, Q5.

| # | Sujet | Décision |
|---|---|---|
| Q7 | Voie Apec | ~~Collage pleine page~~ : choisie, puis **remplacée par Q8** (la restriction d'Apec n'était pas levée pour capturer une vraie copie de page). |
| Q8 | Apec, pour le moment | **Apec se complète à la main** (« Coller la description », C7). « Ouvrir dans le navigateur » n'est plus proposé pour une offre Apec (`BROWSER_REFUSED_SOURCES`), et la route le refuse sans appeler le poste : chaque essai pèserait sur la réputation de l'adresse de Nicolas, celle de la veille. La lecture des offres Apec (collage pleine page ou autre) est reportée à une **étape d'amélioration** (plan §8). Le poste et la lecture assistée restent pour les autres sites. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Poste | Deux demandes à côté de `/preremplir`, sous les mêmes gardes : `/ouvrir {url}` → `{tab}` (jeton aléatoire, réponse une fois la page chargée, 60 s au plus) ; `/lire {tab}` → `{url, html}` (adresse affichée et DOM rendu, `page.content()`, 3 Mo au plus). Registre jeton → onglet sur le seul fil Playwright | Q1 ; un seul fil possède Playwright (D5) |
| Onglet perdu | Onglet fermé, jeton inconnu (poste relancé) : raison en français, « rouvre la fiche » ; jamais de réouverture automatique | Aucun réessai (C1, Q5) |
| Poste dans l'application | Protocole `Workstation` : `open_page`, `read_page` ; client et erreurs communs (`WorkstationUnavailableError`). `app.state.workstation` installé par la composition (`system/web.py`), plus par `candidatures` | Deux modules s'en servent ; aucun import de l'un dans l'autre |
| Même site (Q6) | Règle pure : la page affichée est acceptée si `source_for_url(adresse affichée)` vaut la source de l'offre ou celle de son adresse | Couvre les liens de suivi des alertes (le site d'arrivée est la source de l'offre) |
| Lecture | `parse_page(html, adresse affichée)` puis `enriched(offre, page)` | Moteur C2, identique à l'import et aux alertes |
| Écriture | `enrich_offer_from_page` partage avec `enrich_offer` une seule écriture : offre (`update`, `seen=False`), score recalculé, événement `offres.offer_enriched` (`how: browser`, méthode de lecture, score avant/après), dans **une** transaction. Rien de changé : rien n'est écrit, la raison s'affiche. Aucune adresse dans l'événement | AGENTS §4 ; un lien peut porter un jeton (plan §8, C2 → E3) |
| Réseau | Le poste est appelé hors de toute transaction | Règle de la veille (C6) |
| Écran | Pour une offre incomplète, à côté de « Coller la description » (fiche et tri, gabarit commun) : « Ouvrir dans le navigateur » (touche `n` ; `e` à l'origine, en double avec « Écarté » : changée en H1, choix de Nicolas le 06/10), puis « Lire la page affichée » (jeton d'onglet en champ caché, aucun état côté client) | Q1 ; règles de l'écran Offres |
| Lecteur Apec | Forme décidée sur la capture réelle (Q4) ; jeu anonymisé dans `tests/offres/imports/data/apec/` | Aucun lecteur écrit sur une page inventée (C1) |
| Préremplissage | Reste en sommeil (`PREFILL_ENABLED = False`) | Recette de D5 |

## Décisions prises pendant l'implémentation

| Sujet | Décision | Raison |
|---|---|---|
| Lecteur Apec | Les sections de la page dessinée (« Descriptif du poste », « Profil recherché », « Entreprise » : `h4` suivi de son bloc, dans `.container-details-offer`) sont lues **avant** le JSON-LD (`SECTIONED_PAGES`), sous les mêmes intitulés que le détail public de C1 ; les faits viennent du JSON-LD | Capture du 05/10 : le `JobPosting` de la page ne contient que le descriptif, sans retours à la ligne ; le profil (les compétences du score) n'y est pas |
| Événement | `offres.offer_enriched` : `how` (`pasted`, `browser`), et pour une lecture `method` et `description_read` ; une seule écriture partagée avec le collage (`_write_enrichment`) | Une page qui ne donne que des faits (Q3) se distingue d'une description lue |

## Mesures

| Contrôle | Résultat |
|---|---|
| Essai réel n° 1 (05/10, 13:43, Q4) : fiche Apec 179509139W ouverte par le poste | **Défi DataDome passé à la main**, annonce affichée ; page dessinée lue (164 000 caractères), JSON-LD partiel ; capture anonymisée dans `tests/offres/imports/data/apec/rendered.html` |
| Vérification globale | 1 508 tests verts ; 2 min 51 sous une charge de 11,7 (navigateur, autre processus Python) : mesure de référence sur GitHub |
| Application dans Docker → poste (`host.docker.internal:8765`) | Joint (lecture d'un onglet inconnu : raison rendue) |
| **Recette n° 1 (Nicolas, 05/10, 14:00)** : offre Apec 520, « Ouvrir dans le navigateur » | **Bloqué par Apec** : « Access is temporarily restricted — We detected unusual activity from your device or network », motif « Automated (bot) activity on your network ». Aucun défi à passer. Rien n'a été écrit (aucune lecture demandée). **Arrêt (Q4)** : aucun nouvel essai, aucun maquillage du navigateur |

## Hors E5

Réveil du préremplissage (D5) ; lecture assistée sur un VPS sans écran (plan §5) : la description collée reste la voie
universelle ; lecture des offres Apec (Q8).

## Clôture (Nicolas, 05/10)

**Étape close par décision de Nicolas** : lecture assistée livrée (poste `/ouvrir` et `/lire`, lecteur des pages Apec
dessinées, refus d'une page d'un autre site, faits seuls quand la description n'est pas lisible, écran à deux temps).
Critère « une offre Apec incomplète enrichie depuis sa fiche » **non atteint par la lecture assistée** : Apec refuse
le navigateur piloté (recette n° 1) ; une offre Apec se complète à la main (Q8). Reprise d'Apec : étape d'amélioration
(plan §8). Vérification globale verte : locale 1 510 tests en 1 min 43 (charge 9,5) ; GitHub 1 510 tests en 1 min 39
(passage `37311810222`).
