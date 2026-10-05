# E4 — Décisions et écran

Date : 05/10/2026 · Étape : E4 (plan v2, avancée avant E3) · Préparation : *grill me* avec Nicolas (Q1–Q12) puis mode plan

Critère de sortie (plan) : « Aucun changement de statut ne passe inaperçu ».

## Constats de départ

| Constat | Source |
|---|---|
| E2 écrit une décision par message, sans jamais changer d'étape ; « À vérifier » n'a aucun geste | `rocky/messages/classification/usecases.py` (`_write`), décision E2 (Q1, Q14) |
| `message_decisions.author` accepte `user` et le reclassement ne passe jamais par-dessus, mais aucun code n'écrit de décision `user` | migration `0014`, `classification/usecases._already_decided` |
| La transition automatique bornée existe : `change_stage(author=RULE)` refuse une régression ou une sortie d'issue (`automatic_transition_allowed`) | `rocky/candidatures/usecases.py`, `rules.py` (D1, Q5) |
| La décision sur un message et le changement d'étape s'écrivent aujourd'hui chacun dans sa transaction : `_write` sur la connexion de `messages`, `change_stage` sur celle d'une route | `messages/sql.py` (`SqlStorage`), `candidatures/web.py` |
| Un dossier exige une offre (`applications.offer_id NOT NULL`) : les candidatures faites hors de Rocky n'y existent pas, et aucun message de Nicolas n'était rattaché à la recette d'E2 | migration `0006`, recette E2 |
| L'employeur que nomme une plateforme est gardé dans la preuve `employer.cited` (JSONB `proofs`), pas dans les colonnes | `classification/rules.py`, décision E2 (Q22) |
| Aucune notion de « vu » ni de compteur dans la navigation ; seul `add_notice` pose un bandeau sur toutes les pages | `rocky/system/shell.py` |
| `job_offers.url` est obligatoire et la veille déduplique aussi par adresse | migration `0004`, `offres/sql.py` (`SqlStore.find`) |

## Décisions métier (grill avec Nicolas, 05/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Seuil de la transition | Confiance **haute** : transition appliquée (auteur `rule`), annulable et signalée. Confiance **moyenne** : transition **proposée**, appliquée en un geste. Confiance **faible** : « À vérifier », rien n'est proposé. |
| Q2 | Étape par catégorie | Refus → Refusée ; Entretien, Test → Entretien ; Offre → Offre ; Message de l'employeur → En discussion ; Accusé de réception → fait du dossier, et **Préremplie → Envoyée** (l'accusé prouve l'envoi). Les autres catégories ne changent aucune étape. |
| Q3 | Correction après transition | La transition tirée du message corrigé est **annulée dans la même transaction** que la correction si elle est encore le dernier changement du dossier ; sinon elle reste et l'écran le dit. |
| Q4 | Candidatures faites hors de Rocky | Geste **« Créer la candidature »** depuis un message : offre minimale d'origine « message » (employeur cité, intitulé, lien s'il y en a un) et dossier « Envoyée », dans une seule transaction ; le message y est rattaché (auteur `user`). Rien n'est créé sans geste. |
| Q5 | « Ce qui a bougé » | En tête de 📬 Messages, chaque transition appliquée ou proposée reste **jusqu'à un geste** (Vu, Appliquer, Ignorer, Annuler, Corriger) ; compteur sur l'entrée 📬 de la navigation. F1 reprendra ce bloc dans 🏠 Aujourd'hui. |
| Q6 | Gestes sur un message | « Corriger » : la catégorie (les 10), la candidature (un dossier, aucune, ou en créer une). « Juste » : confirme la décision de Rocky. Chacun écrit une décision `user` : ce sont les étiquettes (D14). |
| Q7 | Correction → règle | Après une correction, case **« Toujours pour cet expéditeur »** : règle du compte « adresse exacte → catégorie ». Une candidature corrigée depuis un expéditeur qui n'est ni ATS ni plateforme propose de **retenir le domaine** de l'employeur du dossier. Règles visibles et retirables. |
| Q8 | Messages d'une même candidature | Liste de 📬 Messages **regroupée par candidature** : le message le plus décisif en tête, « +n messages » dépliable ; les messages sans candidature restent un par un. Le dossier montre tous ses messages dans l'étape Suivi. |
| Q9 | Entretien sans date | Une transition vers Entretien pose la prochaine action **« Fixer la date de l'entretien », J+1** ; l'utilisateur la remplace par « Préparer l'entretien » et sa date. |
| Q10 | Transition non permise en automatique | **Sortie d'une issue** (Sans réponse → Refusée, Sans réponse → Entretien) : proposée. **Retour en arrière** : rien n'est proposé, le message est seulement rattaché. |
| Q11 | « Sans réponse » après un délai | **Hors E4** (F1 ou après) : il faut d'abord des rattachements fiables. |
| Q12 | Offre minimale | Traitée **comme un import** : notée, incomplète, décision « Intéressé » à motif automatique, enrichissable par la description collée. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme du code | Sous-paquet `rocky/messages/decisions/` : `model.py`, `rules.py` (fonctions pures : étape visée, plan de transition, cases offertes, ordre d'un groupe), `usecases.py`. SQL dans `messages/sql.py` | Même forme que `classification/` |
| Liens entre modules | `messages` → `candidatures` et `messages` → `offres` par des fonctions publiques de `candidatures/web.py` et `offres/web.py` qui prennent la **connexion** de la transaction en cours ; jamais le SQL d'un autre module | AGENTS §4 ; même montage que `offres.web.record_application_decision` (D1) |
| Une transaction | `classification._write` appelle un crochet `follow` après `add_decision`, sur la même connexion : décision, transition, ligne `mail_transitions` et événements sont validés ensemble | Plan v2 (E4) ; un changement d'étape n'existe jamais sans sa décision ni l'inverse |
| Décision `user` | Ne déclenche pas de transition automatique : la transition est **proposée sur place** et s'applique en un geste (auteur `user`). Preuve : `Tier.USER` (« Toi »), règles `user.corrected`, `user.confirmed`, `user.created`. `reviews_id` garde la décision revue | Toute transition passe par une décision ; la paire (décision de Rocky, décision de l'utilisateur) est l'étiquette D14 |
| Règles par compte | Catégories **sans candidature** seulement : Approche d'un recruteur, Alerte emploi, Hors recherche. Case non offerte pour un expéditeur d'alerte, relais, d'ATS ou de site d'emploi. Lue en premier par `classify` (règle `account.sender`, niveau haut) ; à sa création, les messages de cette adresse sans décision `user` sont reclassés par les règles | Un relais (Hellowork) corrigé une fois prendrait tout ; l'InMail par `messages-noreply@linkedin.com` et les newsletters sont les cas connus (E2) |
| Domaine retenu | Jamais pour une messagerie publique (`PUBLIC_MAIL_DOMAINS` : gmail.com, outlook, orange.fr…) ; écrit par `set_employer_domain` (D1, E2 Q3) | Un recruteur qui écrit depuis Gmail ne fait pas de gmail.com le domaine de son entreprise |
| Rétroactivité | Aucune transition sur les décisions d'E2 déjà en base | Les transitions naissent avec les décisions d'E4 |
| Offre minimale | `Origin.MESSAGE`, source `message`, identifiant `message-<id>` (création rejouée = même offre, même dossier) ; lien de l'annonce s'il est saisi, sinon le lien du message dans Gmail ; motif automatique `applied_outside` (hors de `REASONS`, comme `application_started`) ; dossier créé à « Envoyée », prochaine action « Relancer » à la date du message + 7 jours. Ensuite, les messages qui citent le même employeur sont reclassés par les règles, sans modèle | Une adresse vide rapprocherait toutes les offres sans lien (`SqlStore.find`) |
| Schéma | Migration `0016` : `message_decisions.reviews_id` ; `mail_transitions` (une par décision au plus, `applied` avec `change_id` ou `proposed`) ; `mail_transition_settlements` (un règlement par transition : vu, appliquée, ignorée, annulée, corrigée) ; `mail_sender_rules` (retrait par une ligne `removes_id`) ; origine `message` des offres. Tout en ajout seul | « Ce qui a bougé » = transitions sans règlement : le critère se lit dans le schéma |
| Journal | `messages.message_classified` (acteur `user`, geste dans le contenu), `messages.transition_recorded`, `messages.transition_settled`, `messages.sender_rule_added` / `_removed` ; `candidatures.stage_changed` d'acteur `rule` porte `message_id` | AGENTS §4 |
| Navigation | `add_badge(app, key, provider)` dans `rocky/system/shell.py`, sur le modèle d'`add_notice` | Le compteur ne fait pas importer `messages` par la coque |
| Jeu étiqueté | `rocky-admin messages-etiquettes <email>` : CSV des décisions `user` et de la décision revue, sur la sortie standard, jamais versionné | Plan v2 (« corrections conservées comme jeu étiqueté ») |

## Hors E4

« Sans réponse » après un délai (Q11, F1 ou après) ; offres tirées des alertes (E3) ; reprise des étiquettes de
l'échantillon de l'archive (E2, recette) avec les corrections de Nicolas.
