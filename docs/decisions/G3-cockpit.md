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

(complétées pendant l'implémentation)
