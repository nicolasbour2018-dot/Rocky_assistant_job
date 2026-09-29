# C6 — Veille

Date : 29/09/2026 · Étape : C6 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q10) puis mode plan

Critère de sortie : « Une panne simulée laisse un statut final explicite et aucune offre orpheline ou sans score. »

## Constats de départ (ancien Rocky, archive A1, étapes précédentes)

| Constat | Source |
|---|---|
| L'ancienne veille jetait les offres sous le seuil (`continue` sans écriture) et ne notait pas les offres incomplètes | `dashboard/rocky/watch.py` (tag `rocky-v1-streamlit`) |
| 54 veilles sur 54 `PARTIAL` : un refus systématique (France Travail, quota TheirStack) rendait chaque veille partielle | `watch_runs.csv` (A1), décision C1 |
| Une veille pouvait rester `RUNNING` ; les écritures se faisaient au fil de l'eau, sans unité | plan §6 |
| Planificateur APScheduler de secours **et** cron système, à midi heure de Paris | `dashboard/rocky/scheduler.py`, `cron/` |
| `collect` dédoublonne les requêtes entre pistes et perd la requête qui a trouvé chaque offre | `rocky/offres/sources/usecases.py`, plan §8 (C1 → C6) |
| Une page importée a pour identifiant son adresse ; la veille garde l'identifiant de la plateforme | plan §8 (C2 → C6) |
| Le score est une fonction pure ; `Score.to_json` est sa forme stockée | décision C4 (Q12) |
| Pistes : suppression définitive interdite dès qu'une offre y est rattachée | décision B5 (Q21), plan §8 (B5 → C6) |
| Sessions et jetons expirés jamais purgés | plan §8 (B3 → C6) |

## Décisions métier (grill avec Nicolas, 29/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Horaire | Une veille par jour à **12 h, heure de Paris**, par le planificateur intégré (D12). Pas de cron. |
| Q2 | Rattrapage | **Bandeau minimal** dans la coque : « Veille en retard depuis … — Lancer maintenant » quand la dernière veille close date de plus de 24 h. Le même bouton lance une veille à la main. F1 le déplacera dans 🏠 Aujourd'hui. Pas de rattrapage automatique. |
| Q3 | Veille partielle | Partielle si la **recherche** d'au moins une source est refusée ou en panne. Un détail refusé (Apec, DataDome) et une requête sautée sont signalés sans rendre la veille partielle. Une source en attente ou non configurée n'est jamais un échec. |
| Q4 | Doublons | **Identité stricte** : une seule offre quand la source et l'identifiant, ou l'adresse, sont identiques. Entre deux sites, une clé de rapprochement (intitulé et employeur normalisés : « Jems Group » = « JEMS ») est stockée pour signaler « vue aussi sur … » en C7. Aucune fusion automatique. |
| Q5 | Recalcul | **Recalcul immédiat, en tâche de fond**, de toutes les offres du compte dès qu'un élément lu par l'analyse ou le score change (pistes, compétences, préférences, langues, expériences, version des règles). Une correction de texte ne déclenche rien. |
| Q6 | Historique des scores | **Un score courant par offre et par piste active**, remplacé à chaque recalcul. En C7, une décision garde une copie du score affiché (étiquette D14). |
| Q7 | Offre déjà connue | **Compléter sans écraser** (`imports.rules.enriched`) : nouvelles pistes ajoutées, date de dernière vue, description complète qui remplace une incomplète, faits vides remplis ; un fait connu n'est jamais écrasé. |
| Q8 | Comptes | La veille planifiée tourne pour **chaque compte activé qui a au moins une piste active**, l'un après l'autre, chacun avec sa propre veille. |
| Q9 | Panne d'une requête | Choix de C1 conservé : une panne (5xx, délai dépassé) arrête la source pour cette veille ; les offres déjà reçues sont gardées et la veille est partielle. Un refus arrête toujours la source. |
| Q10 | Import par URL | Dès C6, « Ajouter à mes offres » sous l'aperçu passe par la même unité d'écriture que la veille. L'offre est rattachée à la **piste où son score est le plus haut** (à aucune si le compte n'a pas de piste active). |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Statuts | `running` → `completed` (terminée), `partial` (partielle), `failed` (échouée), `interrupted` (interrompue). `failed` : aucune source interrogeable n'a répondu, aucune source n'est interrogeable, ou une erreur survient hors des sources (profil illisible, base indisponible). `partial` aussi quand une offre n'a pas pu s'écrire (bogue d'analyse ou de score) | Une veille est toujours close, avec sa raison. |
| Interruption | Une `BaseException` (arrêt du processus) clôt la veille en `interrupted` dans un `finally`, puis se propage. Une veille restée `running` dont le verrou est libre (processus tué) est close en `interrupted` au démarrage suivant | Plus jamais de `RUNNING` éternel. |
| Unité d'écriture | **Une transaction par offre** : l'offre, ses pistes et ses scores. Idempotente : recherche par `(compte, source, identifiant)` puis par adresse, sinon insertion | Une panne au milieu d'une veille ne laisse que des offres complètes ; une veille rejouée n'ajoute rien. |
| Collecte hors transaction | Le réseau (recherche, détail) se fait avant toute écriture ; aucune transaction ne reste ouverte pendant une requête | Une transaction courte ne bloque ni l'écran ni le recalcul. |
| Rattachement aux pistes | `collect` garde, pour chaque offre, les requêtes qui l'ont trouvée ; la veille relie chaque requête aux pistes qui l'ont produite (même clé que `unique_queries`) | D3 sans refaire de requête : deux pistes au même intitulé ne doublent pas les requêtes. |
| Détail | Demandé seulement pour une offre nouvelle ou encore incomplète en base | Pas de requête quotidienne pour un détail déjà lu (volume, C1 Q5). |
| Verrou | Verrou consultatif PostgreSQL par compte (`pg_try_advisory_lock`) autour de la veille et du recalcul | L'application et `rocky-admin veille` ne travaillent jamais en même temps sur un compte. |
| Empreinte | `inputs_hash` : empreinte de `ScoringProfile`, des `account_skills` et des deux versions de règles, gardée avec chaque score. Un score d'une autre empreinte est périmé | Le recalcul (Q5) ne refait que ce qui a changé ; appeler le recalcul après chaque écriture du profil ne coûte rien quand rien ne change. |
| Date du score | Le score d'une offre utilise le jour de son calcul ; un simple changement de jour ne rend pas un score périmé | Seules l'expérience et la date limite en dépendent, faiblement ; la veille suivante recalcule les offres qu'elle revoit. |
| Seuil | Aucun statut stocké : « sous le seuil » et son motif se calculent depuis le score courant (`Score.threshold_reason`) | Plan §3 (indicateurs calculés). |
| Journal | `offres.watch_finished` (statut, déclencheur, compteurs), `offres.watch_interrupted`, `offres.scores_recomputed` (nombre, cause), `offres.offer_added` (import, geste de l'utilisateur). Aucun événement par offre collectée | Les transitions sont tracées ; les compteurs de la veille disent le reste. |
| Garde de la piste | `offer_tracks.track_id` en `ON DELETE RESTRICT` ; `profil` intercepte la violation (point de sauvegarde) et répond « Des offres sont rattachées à cette piste : archive-la plutôt. » | La base fait respecter B5 Q21 ; `profil` ne lit jamais les tables d'`offres`. |
| Planificateur | Boucle maison dans un fil, démarrée par le *lifespan* de l'application : tâches quotidiennes à heure locale (veille à 12 h, purge des sessions et jetons expirés) et recalcul réveillable (après une écriture du profil, et chaque minute). Une tâche en échec est journalisée avec sa trace. `ROCKY_SCHEDULER_ENABLED` (vrai par défaut) l'éteint pour les tests | Pas de dépendance (APScheduler) pour trois tâches ; l'état durable est en base (`watch_runs`). |
| Heure de Paris | `zoneinfo("Europe/Paris")` ; `tzdata` ajouté seulement si l'image n'a pas de base de fuseaux | Le conteneur est en UTC. |
| Commande | `rocky-admin veille <email> [--piste]` : une vraie veille, écrite, avec son compte rendu source par source | Diagnostic et vérification réelle ; même cas d'usage que le planificateur. |
| Forme | `rocky/offres/sql.py` (tables, tout le SQL d'`offres`), `rocky/offres/rules.py` (règles pures), `rocky/offres/usecases.py` (`record_offer`, recalcul), `rocky/offres/watch/` (veille, bandeau) ; `rocky/system/scheduler.py` | AGENTS §4 : règles → cas d'usage → SQL du module → routes. |
