# G3 — Cockpit

Date : 06/10/2026 · Étape : G3 (plan v2) · Préparation : *grill me* avec la skill de design (Q1–Q28), maquette
comparée, puis mode plan

Critère de sortie (fixé au grill, Q26) : depuis le cockpit,

1. une candidature se prépare en **3 clics au plus** (Préparer, une raison, Valider : le dossier est ouvert) ;
2. chaque instrument montre son **delta** et son **graphique** en semaines et en mois ;
3. objectif, séries et jalons sont **recalculés exactement** depuis le journal et les tables existantes (tests) ;
4. **un seul bouton principal** dans chaque état : nouveau compte, problème, normal, rien à faire ;
5. recette de Nicolas ; vérification globale verte en local et sur GitHub.

## Constats de départ

| Constat | Source |
|---|---|
| 🏠 Aujourd'hui est une pile de cartes dans un ordre fixe (veille, messages, relances, dossiers, offres) ; la première carte qui propose une action porte le bouton principal ; repli « Parcourir les offres » | `rocky/system/shell.py` (`TODAY_ORDER`, `main_action`, `BROWSE_OFFERS`) ; décision F1 (Q5, Q13) |
| Le journal d'événements porte le compte et l'instant de chaque décision d'offre, création de dossier, passage d'étape, envoi, veille ; aucune lecture « par compte et par période » | `rocky/system/events.py` ; types `offres.decision_recorded`, `candidatures.application_created`, `candidatures.stage_changed`… |
| « Préparer la candidature » existe : le panneau des raisons d'« Intéressé », puis décision et dossier dans une transaction | `rocky/candidatures/web.py` (`prepare_panel`, `prepare`) |
| Aucune fonction publique ne donne les meilleures offres non décidées : seul l'écran Offres les calcule | `rocky/offres/screen.py` (`queue`), `rocky/offres/web.py` |
| Le compte n'a pas de prénom ; le profil a `full_name` (« Nom ») | `rocky/system/auth/sql.py`, `rocky/profil/model.py` (`Identity`) |
| Rocky ne garde aucune date de visite | — |
| Il faut 7 à 9 gestes d'une offre à l'envoi (tri, préparer, CV, lettre, PDF, envoi, confirmation) : la règle des 3 clics vaut jusqu'au dossier ouvert | `rocky/candidatures/` (parcours du dossier) |
| Aucune bibliothèque de graphiques ; htmx 2.0.11 seul ; mode sombre par `prefers-color-scheme` | `rocky/system/static/` |

## Décisions métier (grill avec Nicolas, 06/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Frontière G3/G7 | G3 : disposition, hiérarchie, composants visuels fonctionnels (anneau, jauges, fil, graphiques) en style neutre, avec les jetons CSS existants. Couleurs, typographie, illustrations, animations : G7. |
| Q2 | Progression | Objectif de la semaine, séries et jalons ; **pas de points d'expérience** (ils récompenseraient le tri plutôt que l'envoi). Tout est calculé depuis le journal et les tables existantes, sans compteur stocké. |
| Q3 | Phrase de motivation | Contextuelle et déterministe (elle cite un fait), repli sur une liste fixe tirée par le jour. |
| Q4, Q27 | Héros | Par priorité : (1) **relance due** (échéance arrivée) ; (2) **dossier prêt** (Prête, Préremplie) ; (3) **dossier en cours le plus avancé**, à égalité la date limite la plus proche ; (4) **meilleure offre** non décidée ; (5) rien : « Lancer la veille » et l'heure du prochain passage. Un problème bloquant (veille en retard ou échouée, boîte à reconnecter) est un bandeau au-dessus du héros. |
| Q5, Q16 | Fil | Colonne chronologique, sans défilement automatique ; **7 jours**, 20 lignes au plus, un lien au plus par ligne. Voix de Rocky : veilles, alertes lues, messages classés, mouvements venus d'un message, offres d'alerte sans adresse (constat H3), dates limites à 3 jours ou moins, relances dues, boîte à reconnecter. Voix de l'utilisateur : envois, jalons, objectif atteint. Les décisions de tri sont regroupées par jour (« 8 offres triées »). Les nouveautés depuis la dernière visite sont marquées. |
| Q6 | Bouton principal | Un seul par état : problème, sinon héros, sinon veille. |
| Q7 | Maquette | Maquette jetable avant le code (Artifact privé) : **disposition A** retenue (instruments en tête, puis l'action à gauche, progression et fil à droite). |
| Q8, Q25 | Écran | Le cockpit **remplace** 🏠 Aujourd'hui sur `/` ; libellé « Cockpit », icône 🧭 (provisoire : les icônes sont l'affaire de G7). |
| Q9 | Objectif de la semaine | Choisi par l'utilisateur, **1 à 10, 3 par défaut**, modifiable depuis le cockpit, rangé dans les préférences du profil. Compte les candidatures qui **atteignent Envoyée** pendant la semaine de Paris (lundi–dimanche), annulations respectées (comme le Bilan). |
| Q10, Q19 | Séries | (a) **jours actifs d'affilée**, du lundi au vendredi : le week-end ne casse pas la série, un geste du week-end compte ; un jour est actif avec au moins une décision d'offre, une étape de dossier, un envoi ou une relance faite (une seule offre triée suffit) ; (b) **semaines d'affilée à l'objectif**. Les jours actifs de la semaine sont affichés (L M M J V). |
| Q11 | Jalons | Démarrage : profil complété, première piste, CV importé, Gmail connecté, première veille ; tri : 10, 50, 100 offres décidées ; premier dossier ; 1, 5, 10, 25, 50 candidatures envoyées ; première réponse humaine, premier entretien, première offre d'emploi. Le dernier jalon atteint et le prochain avec ce qu'il reste ; la liste complète en un clic. |
| Q12 | Nouveau compte | Le héros est la **liste de démarrage** (les 5 jalons de démarrage, chacun avec son lien) jusqu'à la première veille ; rappel après l'onboarding (l'onboarding lui-même : plus tard). |
| Q13, Q20 | Instruments | Quatre cartes : grand chiffre (l'état actuel), **delta** d'un flux par rapport à la semaine précédente **au même jour** (lundi → aujourd'hui contre lundi → même jour), lien vers l'écran filtré. Offres à examiner (dont ≥ 75 ; flux : arrivées au-dessus du seuil, décidées) ; Dossiers en cours (dont prêts ; flux : ouverts) ; Cette semaine (envoyées sur l'objectif, séries ; flux : envoyées, ligne de l'objectif) ; Retours (réponses humaines sur envoyées, dont entretiens ; flux : réponses humaines, entretiens). Une ligne d'état de la veille toujours visible, avec « Lancer la veille » et l'état des boîtes. |
| Q14 | Dernière visite | Repère par compte : l'heure de la visite précédente du cockpit, mise à jour au chargement complet seulement. |
| Q15 | Gestes sur une offre | Préparer la candidature (principal : panneau des raisons, puis dossier) ; Pas pour moi (motifs d'« Écarté » sur place) ; Plus tard (décision écrite) ; Voir l'offre. Pas de geste « Passer » qui n'écrit rien. |
| Q17 | Suggestions | Sous le héros, **les 2 meilleures offres de chaque piste active**, triées par score (choix fait sur la maquette : la plupart des comptes ont 2 ou 3 pistes). |
| Q18 | Salutation | « Bonjour » et le premier mot de `full_name`, sinon « Bonjour ». |
| Q21, Q22 | Carte retournée | Un clic sur la carte la retourne (bouton accessible ; sans animation si les animations sont réduites) ; au verso, Semaine / Mois et « Revenir » ; le graphique se charge à la demande. 12 semaines ou 12 mois ; histogramme SVG produit par le serveur, valeur au survol, tableau pour les lecteurs d'écran, aucune bibliothèque. |
| Q23 | Ton, célébration | Tutoiement, phrases courtes, un fait chacune. Un objectif atteint ou un jalon franchi s'affiche **une fois** en tête du cockpit à la visite suivante (atteint après le repère de visite), puis reste dans le fil ; aucun effet visuel en G3. |
| Q24 | Architecture | La coque dispose les zones ; les modules s'y inscrivent par registres ; la progression vit dans `candidatures` (fonctions pures) ; ce qu'elle ne peut importer lui arrive par un port rempli à la composition ; l'objectif dans `profil`, le repère de visite dans `system`. Pas de cinquième module (D13). |
| Q28 | Blocs d'Aujourd'hui | Veille : bandeau de problème ou ligne de veille ; messages : lignes du fil (« Voir dans Messages », les gestes restent dans 📬) ; relances et dossiers : héros à leur tour, sinon fil et instrument ; offres : instrument, héros, suggestions. Le repli « Parcourir les offres » disparaît. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Coque | `rocky/system/cockpit.py` : formes (`Hero`, `Instrument`, `Series`, `FeedLine`, `Sentence`, `Suggestion`, `Progress`, `Status`), registre `add_cockpit(app, module, Parts(...))` sur `COCKPIT_KEYS` (veille, offres, candidatures, messages), choix purs (`pick_hero`, `main_gesture`, `merge_feed`, `pick_sentence`, `greeting`). Retirés de `shell.py` : `TODAY_ORDER`, `add_today_cards`, la route `/` d'Aujourd'hui ; `candidatures/today.py` disparaît | Q24 ; même modèle de registres qu'en F1 ; `system` n'importe aucun module métier (test d'architecture H4) |
| Parties des modules | `offres/cockpit.py` (héros « offre », suggestions, instrument « Offres à examiner », veilles et tri du fil, offres d'alerte sans adresse), `offres/watch/web.py` (problème de veille, ligne d'état, héros « veille »), `candidatures/cockpit.py` (héros des dossiers et liste de démarrage, trois instruments, progression, envois et jalons du fil, phrases, célébrations, tiroir de 📝), `messages/cockpit.py` (boîte à reconnecter, état des boîtes, mouvements, à vérifier, alertes lues et messages classés par jour, phrase d'une réponse) | Chaque module calcule ses chiffres ; chaque lecture est faite une fois par requête (`request.state`) |
| Progression | `candidatures/progress.py`, pur : `moments_of` (ouverture, envoi, réponse humaine, entretien, offre de chaque candidature : premier changement en vigueur, annulations respectées, mêmes `SENT_STAGES` et `HUMAN_ANSWERS` que le Bilan), `week_of`, `active_day_streak`, `goal_week_streak`, `week_days`, `milestones`, `celebrations` | Q2, Q9–Q11 ; rien n'est stocké |
| Jours actifs | Union des jours (de Paris) des décisions d'offres en vigueur, des changements de candidature écrits par l'utilisateur et des événements `offres.*` / `candidatures.*` d'auteur `user` (`events.user_days`, sur 400 jours) | Q19 : un tri, une étape (lettre, CV), un envoi, une relance ; les tables gardent l'heure de l'horloge de l'application |
| Série hebdomadaire | Calculée avec l'objectif **actuel** (pas l'historique des objectifs) | Simple et lisible ; noté au plan §8 |
| Jalons de démarrage | Profil complété : `onboarding.completed_at` ; première piste et CV importé : premier `profil.track_created` / `profil.profile_imported` (`events.first_occurrences`), sinon « fait » sans date si le profil a une piste ou une expérience ; Gmail : plus ancienne `connected_at` des boîtes (port `cockpit_gmail` rempli par la composition) ; première veille : `offres.api.first_watch_at` | Un compte plus ancien que ses événements garde ses jalons |
| Journal | `system/events.py` : `events_of`, `first_occurrences`, `user_days` (jour de Paris en SQL) | Lectures du journal par compte et par période, absentes jusqu'ici |
| Objectif | Colonne `profiles.weekly_goal` (1–10, 3 par défaut, contrainte en base), `ProfileEditor.set_weekly_goal`, événement `profil.weekly_goal_changed` (pas `preferences_updated` : l'import d'un CV réécrit les préférences, il ne doit pas toucher l'objectif) ; route `POST /profil/objectif`, liste déroulante envoyée au changement | Q9 : un geste |
| Repère de visite | Colonne `accounts.cockpit_seen_at`, `SqlAuthStore.swap_cockpit_visit` (lecture sous verrou puis écriture) ; seule une page entière de `/` l'écrit ; un fragment reçoit la visite précédente par `depuis` | Q14 ; la célébration « une fois » en découle : un jalon daté après la visite précédente |
| Migration | `0019_cockpit` : les deux colonnes, descente complète | `.claude/rules/system.md` |
| Héros « offre » | La meilleure offre de la file du tri **dont la date limite n'est pas passée** ; « Pourquoi » : les compétences du profil citées (caractéristiques du score) et le premier manque. Gestes en panneau (`Action.panel`) chargés à la place des gestes du héros : « Préparer » (`/candidatures/offre/{id}/preparer?contexte=cockpit`), « Pas pour moi » et « Plus tard » (`/offres/{id}/motifs?…&contexte=cockpit`, motifs obligatoires comme partout, D14) ; la décision répond `changed()` | Q15 ; critère 1 : 3 clics jusqu'au dossier ouvert ; une offre à date limite passée reste signalée, jamais proposée (G2, Q7) |
| Ordre du héros | Relance due (la plus en retard), dossier prêt (date limite la plus proche), dossier en préparation (date limite la plus proche, puis échéance), meilleure offre, veille | Q27 ; « le plus avancé » parmi les dossiers en préparation : l'étape ne se lit pas sans la lettre, la date limite départage |
| Veille jamais lancée | Pas de problème : l'étape « Première veille » de la liste de démarrage porte le geste ; la ligne d'état le dit | Vu à l'essai : trois fois le même message, et le bouton principal pris à la liste de démarrage |
| Instruments | Recto rendu avec la page ; verso (`GET /cockpit/instrument/{clé}?periode=semaine|mois`) rendu par le serveur et remplacé par HTMX, animation de retournement en CSS, absente sous `prefers-reduced-motion` ; « Revenir » relit le recto | Q21 ; aucun JavaScript ajouté |
| Graphique | Macro Jinja `chart` : barres SVG sur une seule échelle, `<title>` par barre, ligne d'objectif (semaines seulement), tableau `visually-hidden` | Q22 |
| Veille en cours | Seule la ligne d'état se relit toutes les 15 s (`GET /cockpit/etat`) ; à l'arrêt, elle émet `cockpit-changed` et tout le cockpit se relit | Q13 ; le héros ne bouge pas pendant qu'on le lit |
| Téléphone | Sous 760 px : le héros d'abord, puis les instruments, puis le reste (`display: contents` et `order`) | Vu à l'essai : l'action était sous quatre instruments |

## Essai (06/10)

Instance à part : schéma jetable de `test-db`, compte fictif « Camille Exemple », 60 offres sur 80 jours, 24 décisions,
9 candidatures (envoyées, entretien, refus, prête, en préparation), veilles sur 7 jours ; Chromium (Playwright).

| Contrôle | Résultat |
|---|---|
| État normal (relance due) | Héros « En retard depuis le 16/08 », instruments avec delta, progression, fil (états en tête, puis jours) ; un seul bouton principal |
| État « offre » | « Préparer la candidature » (1) → panneau des raisons à la place des gestes (2 : un motif) → « Préparer la candidature » (3) → `/candidatures/1` : **3 clics** |
| Carte retournée | « Cette semaine » en semaines : barres et ligne « objectif 3 » ; Mois ; Revenir |
| Nouveau compte, téléphone (390 px), sombre | Liste de démarrage en tête, 2 étapes sur 5, « Importer ton CV » en bouton principal ; console sans erreur ni avertissement |

Corrigé pendant l'essai : sélecteur d'objectif pleine largeur, série répétée dans « Cette semaine », delta sur trois
lignes, « Évolution » sans allure de bouton, lien du fil à la ligne, point de l'anneau à 0, « Trier » sur chaque veille
du fil, problème de veille jamais lancée, ordre sur téléphone.

Vérification globale (`docker compose run --rm --build check`) : **1 735 tests**, verte, 73,6 s de pytest et 1 min 18
au total (charge moyenne 6) ; un premier passage, le poste plus chargé, a pris 110 s de pytest et 2 min 00 au total.
Garde-fou : 34 cas sur 34.

## Recette

Premier retour de Nicolas (06/10) : « c'est pas mal comme base », mais un clic affichait une miniature de la page dans
la page. Cause : le conteneur du cockpit (et la ligne d'état pendant une veille) portait `hx-target="this"` et
`hx-swap="outerHTML"`, hérités par les liens et formulaires boostés qu'il contient : la page suivante remplaçait le
cockpit au lieu du `<body>`. Corrigé : les relectures sont demandées par des éléments vides et cachés
(`test_no_gesture_of_the_cockpit_inherits_a_target`) ; vérifié dans Chromium (« Trier les offres », « Lancer la veille »,
« Revenir »).

Sur son compte (critère 5) : `docker compose run --rm --build migrate` puis `docker compose up -d --build --wait app`,
http://127.0.0.1:8000/. **Étape close par Nicolas le 07/10** : critère vérifié par les tests, l'essai et sa recette.
