# D1 — Dossier et statuts

Date : 29/09/2026 · Étape : D1 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q9) puis mode plan

Critère de sortie : « Une panne injectée pendant l'annulation ne laisse aucun état contradictoire. »

## Constats de départ

| Constat | Source |
|---|---|
| L'ancien Rocky annule une transition en **deux transactions** : `revert_application_event` marque l'événement annulé, valide, puis `update_application_status` restaure le statut dans une seconde transaction. Une panne entre les deux laisse un événement « annulé » et un statut inchangé | `dashboard/rocky/repository.py` (`revert_application_event`), plan §6 |
| L'ancien Rocky stocke le statut courant (`applications.status`) **et** l'historique (`application_events`) : deux vérités à garder d'accord | `database/schema.sql` |
| Dix statuts, dont « accusé de réception » compté comme une réponse | `dashboard/rocky/application_statuses.py` ; plan F1 (accusé ≠ réponse humaine) |
| Les relances vivent dans les notes libres | plan §6 (« Relances perdues dans les notes ») |
| Les décisions sur les offres sont en ajout seul, l'état en vigueur est calculé (`effective_decisions`) ; une décision est l'étiquette D14 | décision C7 (Q1, Q8) |
| `rocky/candidatures/` est vide ; `/candidatures` est une page vide de la coque | `rocky/system/shell.py` |

## Décisions métier (grill avec Nicolas, 29/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Étapes | En avant : `preparing` En préparation → `ready` Prête à envoyer → `prefilled` Préremplie → `sent` Envoyée → `in_discussion` En discussion → `interview` Entretien → `offer` Offre. Issues : `rejected` Refusée, `withdrawn` Retirée (par toi), `no_response` Sans réponse. L'accusé de réception est un **fait** noté sur le dossier (étapes E), pas une étape. |
| Q2 | Création | Un **geste explicite** « Préparer la candidature » dans la fiche d'une offre. Une décision « Intéressé » ne crée rien toute seule. |
| Q3 | Prochaine action | **Une seule** par dossier (libellé + date), **proposée** à chaque étape (tableau ci-dessous), toujours modifiable ; « Différer » de +1, +3 ou +7 jours. Chaque changement est journalisé. |
| Q4 | Interface | **Minimale** : bouton dans la fiche d'une offre, liste brute à `/candidatures` (étape, prochaine action, changer d'étape, différer, annuler). L'écran 📝 Candidatures est l'étape D6. |
| Q5 | Transitions | **Libres pour l'utilisateur** : en avant, en arrière, vers une issue, réouverture d'une issue, en un geste. Les transitions **automatiques** (messages, E4) sont bornées : jamais de régression, jamais de sortie d'une issue. La règle est écrite et testée dès D1. |
| Q6 | Annuler | Défait le **dernier changement du dossier** (création, étape ou prochaine action) ; plusieurs « Annuler » remontent l'historique, même le lendemain. Rien n'est supprimé : une ligne d'annulation et un événement s'ajoutent. |
| Q7 | Dossiers par offre | **Un seul**, rouvrable : un dossier clos peut être rouvert, jamais dupliqué ; « Préparer » ouvre le dossier existant. |
| Q8 | Lien avec la décision (D14) | « Préparer » sur une offre **sans décision ou « Plus tard »** enregistre **Intéressé**, avec le motif automatique `application_started` (« candidature préparée ») **et au moins un motif d'Intéressé choisi** dans un petit panneau (motifs de C7 ; `other` exige une précision). Sur une offre déjà « Intéressé », le dossier s'ouvre sans nouvelle décision. Sur une offre **écartée**, le geste est refusé avec un message. `application_started` n'apparaît jamais dans le panneau de tri de l'écran Offres : les touches 1–9 ne bougent pas. |
| Q9 | Annuler la création | Défait le dossier **et** la décision « Intéressé » écrite avec lui (l'offre retrouve sa décision d'avant), **dans une seule transaction**. Cas central du critère de sortie. |

### Prochaines actions proposées (Q3)

| Étape | Proposition |
|---|---|
| En préparation | « Finir le dossier », J+2 |
| Prête à envoyer | « Envoyer la candidature », J+2 |
| Préremplie | « Confirmer l'envoi », J+1 |
| Envoyée | « Relancer », J+7 |
| En discussion | « Relancer », J+7 |
| Entretien | « Préparer l'entretien », date saisie (obligatoire) |
| Offre | « Répondre à l'offre », J+3 |
| Issues | aucune |

« Différer » part de la date la plus tardive entre l'échéance et aujourd'hui : une action en retard différée d'un
jour n'est plus en retard.

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Modèle | **Ajout seul, état calculé** : `applications` (identité du dossier, unique par compte et offre) et `application_changes` (création, étape, prochaine action, annulation). L'étape et la prochaine action en vigueur se calculent sur les changements non annulés (`rules.dossier`), jamais stockées | Même forme que `job_decisions` (C7) ; il n'y a plus deux vérités à garder d'accord : un état contradictoire est impossible par construction. |
| Étape et action | Une création ou un changement d'étape fixe **aussi** la prochaine action (la proposition, éventuellement modifiée, ou aucune pour une issue) | Annuler un changement d'étape rend l'étape **et** l'action d'avant, en une ligne. |
| Transaction | Chaque cas d'usage écrit ses lignes et ses événements dans la transaction de la route ; l'annulation d'une création annule aussi la décision écrite par « Préparer » (`decision_id`) par l'API d'`offres`, sur la même connexion | Q9, critère de sortie. |
| Concurrence | Tout changement verrouille d'abord la ligne du dossier (`SELECT … FOR UPDATE`) ; une annulation ne vise qu'une fois un changement (`cancels_id` unique) | Deux clics simultanés s'exécutent l'un après l'autre ; la base refuse une double annulation. |
| Lien avec `offres` | `candidatures` passe par un port (`OfferDecisions`) branché sur des fonctions publiques d'`offres/web.py` (`decision_in_force`, `record_application_decision`, `cancel_application_decision`, `offer_headings`), sur le modèle de `profil.web.stored_profile` ; jamais par le SQL d'`offres`. La fiche d'offre charge l'encart du dossier par HTMX (`/candidatures/offre/{id}`) : `offres` ne connaît qu'une URL | AGENTS §4 ; dépendance dans un seul sens (`candidatures` → `offres`). |
| Motif automatique | `APPLICATION_STARTED` hors de `REASONS` (le panneau de tri ne change pas), connu de `reason_label` ; `application_decision` valide les motifs choisis par `make_decision` puis place `application_started` en tête | Q8 ; un code publié ne se renomme plus. |
| Journal | `candidatures.application_created`, `candidatures.stage_changed`, `candidatures.next_action_set` (avec `deferred_days` pour un report), `candidatures.change_cancelled` ; plus `offres.decision_recorded` / `offres.decision_cancelled` pour la décision liée | Toute transition est inscrite dans `events` (AGENTS §4). |

## Mesures (29/09/2026)

| Contrôle | Résultat |
|---|---|
| **Critère de sortie** (`tests/candidatures/test_sql.py`, vraies transactions PostgreSQL comme une route) | Panne injectée juste après **chaque écriture** de l'annulation : ligne d'annulation, annulation de la décision de l'offre (ligne et événement `offres`), événement `candidatures.change_cancelled`. Pour l'annulation d'une **création** (3 points) et d'un **changement d'étape** (2 points), l'état relu est identique à l'avant : étape, prochaine action, décision en vigueur de l'offre, nombre de changements, nombre de décisions, journal |
| Le test détecte le défaut d'origine | Mutation temporaire : l'adaptateur valide sa transaction après avoir annulé la décision (comme `revert_application_event`). Les points « décision » et « événement » échouent ; code restauré |
| Tests automatiques | Règles (`test_rules.py`, 29 tests), cas d'usage avec faux adaptateurs (`test_usecases.py`), SQL et contraintes (`test_sql.py` : un dossier par offre, une seule annulation par changement, changements incohérents refusés par la base), écran par HTTP (`test_web.py`, 11 tests : encart, motifs, liste, entretien daté, annulations, sans HTMX, 404 pour un autre compte) ; `offres` : `application_decision`, `cancel_decision` |
| Vérification globale | `docker compose run --rm --build check` : 799 tests, 28 s |
| Essai dans Chromium (Playwright, instance à part : schéma jetable de `test-db`, 3 offres semées dont une « Plus tard ») | Fiche → encart « Préparer la candidature » → motif « métier visé » → « En préparation, Finir le dossier le 01/10/2026 » ; liste : « Envoyée » → « Relancer — 06/10/2026 » ; « +3 j » → 09/10 ; « Annuler » ×3 → 06/10, « En préparation », puis « Aucune candidature en cours ». Contrôle en lecture seule : 6 changements pour 6 événements `candidatures.*`, l'« Intéressé » (`application_started`, `target_job`) annulé et « Plus tard » de nouveau en vigueur. Console sans erreur |

## Critère de sortie et clôture (Nicolas, 29/09)

Essai réel par Nicolas sur son compte d'essai (base de développement, migration `0006`), dont « Préparer » sur une offre
à examiner ; contrôle en lecture seule (transaction annulée) :

| Contrôle | Résultat |
|---|---|
| Dossiers | 2 dossiers ; 6 changements (2 créations, 2 changements d'étape, 2 annulations) |
| Traçabilité | **6 changements pour 6 événements** `candidatures.*` ; aucun changement sans événement |
| Lien avec la décision (Q8) | L'offre à examiner est passée en « Intéressé » avec `application_started`, `target_job`, `skills_match`, `location` (motifs choisis dans le panneau) ; l'autre dossier s'est ouvert sans nouvelle décision |

**Étape validée par Nicolas.** Suite : D2 (CV maître et rendu).
