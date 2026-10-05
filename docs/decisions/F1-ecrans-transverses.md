# F1 — Écrans transverses

Date : 05/10/2026 · Étape : F1 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q14) puis mode plan

Critère de sortie (plan) : « Chaque écran a une action principale claire ».

## Constats de départ

| Constat | Source |
|---|---|
| A1 → E5 terminées ; `refonte` égale à `origin/refonte` ; vérification verte en local (1 510 tests, 1 min 13 au total) et sur GitHub (1 min 39, passage `37311810222`) | plan v2 §4, décision E5 |
| `/`, `/bilan` et `/systeme` rendent la page générique `empty.html` (« arrive à l'étape F1 ») ; le tiroir 🐾 est un `popover` au texte d'attente | `rocky/system/shell.py` (`_empty_page`), `templates/layout.html` |
| Le bandeau de veille (en retard, en cours, échoué) est une notice de **toutes** les pages, avec « Lancer maintenant » | `rocky/offres/watch/web.py` (`add_notice`), décision C6 (Q2) |
| Lectures existantes : `WatchService.state`, `source_runs` (`watch_run_sources`) ; `candidatures.web.rows_of`, `rules.tabs_of` ; `MessagesService.state`, `pending_count`, `MailboxView` ; `alert_readings` / `alert_offers` sans lecture agrégée | `offres/watch/`, `candidatures/web.py`, `messages/service.py`, `messages/sql.py` |
| Le planificateur ne garde en mémoire que le prochain passage et la file ; un échec de tâche n'est qu'écrit dans les logs. Veille et collecte ont leur historique en base (`watch_runs`, `mail_syncs`), pas la purge ni le recalcul | `rocky/system/scheduler.py`, `rocky/system/web.py` (`_plan`) |
| `messages` importe déjà `candidatures` : l'inverse ferait un cycle | `messages/service.py`, `messages/links.py` |
| Seul l'écran Offres a des raccourcis clavier (aide `?`) | `offres/templates/offres/page.html` |

## Décisions métier (grill avec Nicolas, 05/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Préalables du plan §8 | Aucun : lieux structurés, date limite dépassée et blocs projets du CV restent à leur étape cible. |
| Q2 | Tiroir 🐾 | Contextuel **sans modèle de langue**, déterministe. |
| Q3 | « Sans réponse » après un délai | **Hors F1** : aucune transition automatique ; constat reporté (plan §8). |
| Q4 | Découpage | Une étape, un commit par écran, recette de Nicolas écran par écran. |
| Q5 | 🏠 Aujourd'hui | Blocs dans un ordre fixe : veille (si en retard, en cours ou échouée), messages (ce qui a bougé, à vérifier), relances dues, dossiers à finir, offres à examiner. Le **premier bloc qui propose une action porte le bouton principal**, les suivants un lien. Rien à faire : état vide qui le dit. |
| Q6 | Bandeau de veille | **Déplacé** dans Aujourd'hui (décision C6, Q2) : plus de notice sur les autres pages ; compteur sur 🏠 quand la veille est en retard ou a échoué. |
| Q7 | Messages dans Aujourd'hui | **Résumé** (une ligne par changement) et « Voir dans Messages » ; les gestes (Vu, Appliquer, Ignorer…) restent dans 📬. |
| Q8 | Planification | **Sans nouvelle table** : prochain passage de chaque tâche (mémoire du planificateur) ; dernier passage de la veille et de la collecte lu dans leurs tables. La persistance des échecs de tâche est notée au plan §8. |
| Q9 | 📈 Bilan | Dénominateur : les candidatures qui ont atteint « Envoyée ». « x sur N » pour : accusé de réception seul (message classé accusé, sans réponse humaine), réponse humaine (En discussion, Entretien, Offre ou Refusée atteinte), entretien, offre. Calculé depuis les changements (annulations respectées), sans table. |
| Q10 | Bilan : période, action | Depuis le début (date de la première candidature envoyée affichée) ; action principale : voir les candidatures en attente de réponse. |
| Q11 | ⚙️ Système | Données du compte : dernière veille par source, boîtes Gmail et dernière collecte, alertes par plateforme sur 7 jours, prochains passages. Le **premier problème porte le bouton** (Reconnecter la boîte, Relancer la veille) ; sinon « Lancer la veille maintenant ». |
| Q12 | Contenu du tiroir | « À faire ici » (1 à 3 actions tirées des données de l'écran) et raccourcis clavier de l'écran, chargé à l'ouverture. |
| Q13 | Architecture | **Registres de la coque**, sur le modèle d'`add_notice` / `add_badge` : chaque module inscrit son bloc Aujourd'hui, son panneau Système et son tiroir ; `system` ordonne et rend, sans importer de module métier. Le Bilan vit dans `candidatures` et lit les accusés par un port rempli à la composition. |
| Q14 | Vérification du critère | Un test par écran et par état (vide, problème, normal) : **exactement un bouton principal** ; puis recette de Nicolas. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme d'un bloc | `shell.Card` : titre, lignes, détails (libellé, valeur), au plus une action (`shell.Action` : libellé, adresse, `post`), drapeaux `problem` et `polling`. La coque rend le bouton principal sur la carte que désigne `main_action` (premier problème qui a une action, sinon première action), un bouton simple sur les autres ; sans action, l'action de repli de l'écran (« Parcourir les offres ») | Le critère « une action principale » se tient à un seul endroit, testable sans les modules |
| Registres | `add_today_cards`, `add_system_cards`, `add_drawer` sur le modèle d'`add_badge` ; l'ordre est fixé dans `shell.TODAY_ORDER` et `SYSTEM_ORDER`, une clé inconnue est refusée. `add_notice` et la page générique `empty.html` disparaissent avec leur dernier usage, ainsi que `NavEntry.arrives_in` ; le texte `purpose` de chaque entrée s'affiche sous le titre | Pas de code mort ; l'ordre de Q5 se lit en un endroit |
| Veille en cours | La carte de veille demande la relecture de tout l'écran toutes les 15 s (`polling`) ; « Lancer maintenant » renvoie à Aujourd'hui, ou à Système avec `retour=systeme` (valeur fixe) | Plus de fragment `/veille/bandeau` ; à la fin d'une veille, le compteur d'offres est relu en même temps |
| Compteur de 🏠 | 1 quand la veille est en retard ou a échoué et que le compte a une piste active ; 0 pendant une veille | Q6 |
| Relances dues / dossiers à finir | « Relances dues » : action due d'une candidature envoyée (`FOLLOW_UP_STAGES`) ; « Dossiers à finir » : candidatures avant l'envoi (`BEFORE_SENDING`). `rows_of` lu une fois par requête pour les deux blocs (`candidatures/today.py`) | Constat D6 → F1 : pas de seconde lecture |
| Messages | `MessagesService.attention` : ce qui a bougé et le nombre de décisions de confiance faible (`SqlStore.to_check`, même filtre que la vue « À vérifier ») ; trois lignes au plus, les autres comptées | Q7 |
| Sources dans Système | La dernière veille terminée (`watch_run_sources`), une ligne par source sur le modèle de `report_lines` (`watch.web.source_line`) : état, offres, incomplètes, requêtes sautées, détail arrêté, indice d'une source en attente | Constat C1 → F1 |
| Alertes dans Système | `SqlStore.alerts_by_platform` sur `alert_readings` et `alert_offers` : alertes lues, non lues, offres, nouvelles, fiches refusées, par plateforme sur 7 jours ; les alertes sans lecteur à part | Constat E3 → F1 |
| Planification | Panneau enregistré par la composition (`system/web.py`, `TASKS`) : ce que fait chaque tâche, quand, et son prochain passage (`Scheduler.next_run`), sauf le recalcul (regardé chaque minute) ; planificateur éteint = problème sans geste | Q8 ; la composition seule connaît les tâches |
| Bilan | `candidatures/report.py`, fonction pure sur les changements en vigueur (`standing`) : « envoyée » = Envoyée, En discussion, Entretien, Offre, Refusée ou Sans réponse atteinte (Retirée seule ne compte pas) ; date de départ au jour de Paris. Les accusés : port `Acknowledged`, rempli par `MessagesService.acknowledged_applications` dans `system/web.py` | Q9, Q13 ; `messages` importe déjà `candidatures` |
| Tiroir | Chargé à l'ouverture du `popover` (`hx-trigger="toggle[newState=='open']"`), trois actions au plus. Offres : trier, compléter les incomplètes, importer, et les raccourcis (même liste que l'aide « ? », `offres.web.SHORTCUTS`) ; Candidatures : les dossiers dont l'action est due ; Messages : ce qui a bougé, à vérifier, relever ; Bilan : son action principale ; Profil : une piste à définir, sinon le CV ; Aujourd'hui et Système : les gestes de leurs cartes, le principal d'abord | Q12 ; aucune liste de raccourcis en double |

## Mesures et essai (05/10)

| Contrôle | Résultat |
|---|---|
| **Critère, par les tests** | Pour chaque écran et chaque état (vide, problème, normal, veille en cours), **exactement un** `btn-primary` : `tests/system/test_shell.py` (cartes factices, ordre, repli, problème en premier, fragment de relecture), `tests/offres/test_web.py` (Aujourd'hui avec les vrais modules : veille en retard en tête et bouton principal, offres à examiner en bouton simple), `tests/offres/watch/test_web.py` (Aujourd'hui et Système selon l'état de la veille), `tests/candidatures/test_report_web.py` (Bilan avant et après un envoi) |
| Règles pures | Blocs des candidatures (`test_today.py`), des messages (`test_today.py`, `test_system.py`), Bilan (`test_report.py` : dénominateur, accusé seul ≠ réponse, annulation, jour de Paris), panneau du planificateur, lignes des sources |
| SQL | `to_check` égale la vue « À vérifier » ; `alerts_by_platform` (Hellowork lue avec une fiche refusée, format inconnu à part) ; `acknowledged_applications` (accusé rattaché à French bee, accusé Hellowork sans candidature exclu) |
| Vérification globale | `docker compose run --rm --build check` : **1 556 tests**, verte, 53 s au total (49 s de tests) |
| Essai dans Chromium (instance à part : schéma jetable de `test-db`, compte fictif, 7 offres, 4 candidatures, une veille partielle vieille de 26 h, planificateur éteint) | 🏠 : « Veille en retard » en tête avec « Lancer maintenant » seul bouton principal, compteur « 1 » sur 🏠, relance due de French bee, dossier Valeo à finir, 2 offres à examiner ; ⚙️ : la dernière veille source par source (Apec et sa requête sautée, LinkedIn refusé, France Travail en attente), « Relancer la veille » en bouton principal, Gmail non configuré, planificateur éteint signalé ; 📈 : « 3 candidatures envoyées depuis le 25/09/2026 », réponse 2 sur 3, sans nouvelles 1 sur 3 ; 🐾 sur Offres : trois actions et les raccourcis, chargés à l'ouverture. Console sans erreur ni avertissement |

Corrigé pendant l'essai : la carte du Bilan prenait toute la largeur (alignée sur les autres écrans, 880 px).

## Recette et clôture (Nicolas, 05/10)

Étape close par Nicolas sur le critère vérifié par les tests et l'essai : chaque écran a une action principale claire.
L'UX et l'UI de l'ensemble de Rocky seront **retravaillées dans une étape à part**, hors F1 (plan §8) ; aucune
retouche visuelle des écrans transverses n'est faite ici.

Vérification GitHub verte (passage `37361566948`) : 1 556 tests en **2 min 01** (1 min 39 à E5 pour 1 510 tests),
au-dessus de la limite des 2 min ; en local, 49 s. Voir plan §8 (E4 → B1).
