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
| Forme d'un bloc | `shell.Card` : titre, lignes, action (`shell.Action` : libellé, adresse, `post`), drapeau `problem` et `polling` ; la coque rend le bouton principal (`btn-primary`) sur la première carte qui a une action (Système : le premier problème d'abord), un lien sur les autres | Le critère « un bouton principal » se tient à un seul endroit, testable sans les modules |
| Veille en cours | La carte de veille demande le rafraîchissement de toute la liste d'Aujourd'hui toutes les 15 s (`polling`) ; à la fin, les compteurs d'offres sont relus en même temps | Plus de fragment `/veille/bandeau` à part ; « Lancer maintenant » renvoie à Aujourd'hui |
| Dossiers à finir / relances dues | « Relances dues » : action due d'une candidature envoyée (`FOLLOW_UP_STAGES`) ; « Dossiers à finir » : candidatures avant l'envoi (`BEFORE_SENDING`) ; lus par `rows_of` | Constat D6 → F1 : pas de seconde lecture des dossiers |

*(Mesures, essai et recette : complétés à la clôture.)*
