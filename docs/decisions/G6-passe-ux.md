# G6 — Passe UX des écrans

Date : 07/10/2026 · Étape : G6 (plan v2) · Préparation : audit UX du code, *grill me* avec la skill de design
(Q1–Q28), prototype de Codex (`docs/procedures/g6-ux/rocky-g6.html`), puis mode plan

Critère de sortie (fixé au grill, Q26) :

1. **Défauts** : A1–A9 (ci-dessous) ont chacun un test qui échouait avant ; un test transversal vérifie qu'aucun
   geste boosté n'hérite d'une cible, sur toutes les pages ;
2. **un bouton principal**, exactement, par écran et par état (vide, normal, problème) : Offres (Explorer, Mode
   focus), Messages, chaque étape du dossier, chaque section du Profil, Bilan, Système ; **seule exception** : les
   trois gestes de décision sur une offre ont le même poids, sans bouton principal (R7) ;
3. **parcours chiffrés** (tests HTTP et essai Chromium) : « À préparer » → « Envoyée » en **5 clics au plus** sans
   Gemini ; une décision au clavier sans frappe perdue (`i`, `1`, `Entrée` sans pause) ; relance due en 2 clics et
   dossier depuis le cockpit en 3 clics toujours tenus ;
4. **aucune erreur muette** : tout refus d'un geste HTMX s'affiche dans `#erreur` (Messages, Offres) ;
5. **lexique** : un nom par chose ; un test refuse dans les gabarits les synonymes écartés ;
6. **Bilan** : chaque chiffre recalculé exactement (fonctions pures, mêmes définitions que le cockpit) ; chaque chiffre
   mène à sa liste filtrée ;
7. **Système** : état et raison de chaque module ; derniers passages lus dans la table des passages planifiés ; partie
   « Application » invisible hors `ROCKY_ADMIN_EMAILS` (test) ;
8. **recettes et vérification** : recette de Nicolas sur l'artifact avant le bloc 1, dans l'application après le
   bloc 7 ; vérification globale verte en local (moins de 3 min) et sur GitHub (pytest sous 150 s).

## Constats de départ (audit du 07/10, sur le code)

L'application n'a pas été lancée : l'audit lit les gabarits, les routes, `rocky.css` et `rocky.js`.

### Défauts qui cassent un parcours

| # | Écran | Fait | Référence |
|---|---|---|---|
| A1 | Système | Pendant une veille ou un relevé, `#cards` porte `hx-target="this" hx-swap="outerHTML"` : un geste boosté d'une carte (« Reconnecter la boîte », « Connecter une boîte Gmail », « Définir une piste ») afficherait la page suivante dans l'écran (constat G3 → G6) | `rocky/system/templates/cards.html:3` |
| A2 | Tiroir 🐾 | Les liens « D'après : » héritent de `hx-target="#drawer-content"` : la page s'ouvrirait dans le tiroir | `rocky/system/templates/layout.html:67-68`, `assistant/talk.html:16` |
| A3 | Système, Cockpit | « Relever maintenant » boosté reçoit le fragment de Messages au lieu de la redirection ; « Connecter une boîte Gmail » boosté suit mal la redirection vers Google (Messages a `hx-boost="false"`, pas les autres) | `rocky/messages/web.py` (`collect_now`), `card_action.html`, `cockpit/macros.html` |
| A4 | Messages | Les refus des gestes répondent en 4xx : HTMX 2 ne les affiche pas | `rocky/messages/web.py` (`_content(..., status_code=…)`) |
| A5 | Messages | Pendant un relevé, tout le contenu est relu toutes les 3 s : panneau « Corriger », sélection et plis effacés | `rocky/messages/templates/messages/content.html:4` |
| A6 | Dossier | « Valider cette lettre » refusée perd les paragraphes modifiés ; « Adapter à l'annonce » écrase ce qui n'est pas enregistré | `rocky/candidatures/dossier_web.py` |
| A7 | Dossier | « Envoyée » depuis une candidature close mène à une étape Envoi sans formulaire (constat Revue H → G6) | `follow_step.html`, `rules.journey`, `send_step.html` |
| A8 | Offres | Frappes perdues (constat B4 → C7) : une touche cherche `[data-key]` au moment de la frappe ; pendant l'arrivée d'un fragment, elle ne trouve rien | `rocky/system/static/rocky.js` |
| A9 | Offres | Des refus répondent `Response(status_code=404/422)` sans corps : rien ne s'affiche | `rocky/offres/web.py` |

### Frictions

| Écran | Constats |
|---|---|
| Coque | Aucun signe d'attente (navigation, Gemini, PDF, import de CV) hors tiroir et import d'offre ; aucun message de succès commun ; dates sans année |
| Offres | Trois décisions de même poids, aucun principal ; deux chemins « Préparer » (tri avec touches, fiche sans touches, questions différentes) ; fiche, filtres et position hors de l'URL ; « Trier »/« Liste » oublient les filtres ; une décision depuis la fiche relit la liste depuis le haut ; « Annuler » en Tri seulement ; « N sous le seuil » mène à toutes les offres ; import par URL sans lien vers l'offre ; versions de règles affichées ; informations doublées |
| Candidatures | 9 clics au minimum d'« Intéressé » à « Envoyée » ; « CV prêt » n'enregistre rien ; PDF à générer à la main ; chaque geste du dossier recharge la page en haut ; étape et action montrées deux fois ; Suivi : 6–7 boutons d'étape et 3 plis ; plusieurs principaux ; « Préremplie » proposée alors que le préremplissage dort ; « empreinte » affichée ; `dossier_web.py` de 1 782 lignes |
| Messages | Seul principal : « Relever maintenant » ; réglages Gmail entre « Ce qui a bougé » et la liste ; 10 onglets ; chaque geste relit tout le contenu ; « Corriger » sans « Fermer » ; aucun « Tout vu » ; « version N », « par l'IA » affichés |
| Bilan | Aucun repère dans le temps ; « dont entretien » divisé par les envoyées ; « Sans nouvelles » ≠ étape « Sans réponse » |
| Profil | Une page de 7 sections ; libellés anglais (« Download in English », « Preview », « Check my CV ») ; « Modifier » hors URL ; plusieurs principaux dans le kit ; noms des lecteurs PDF affichés ; import de CV sans attente visible, hash dans l'URL |
| Système | Nom de variable d'environnement affiché ; « diagnostics » promis, absents ; toutes les cartes relues toutes les 15 s |
| Vocabulaire | « Annuler » (défaire ou abandonner une saisie) et l'état « Annulée » ; « Écarté » / « Pas pour moi » / « Pourquoi écartée ? » ; « Sans réponse » / « Sans nouvelles » ; « Prêtes » / « Prête à envoyer » ; « Suivi » onglet et étape ; « collecte » / « relevé » ; trois libellés pour lancer la veille ; « Offre » étape et écran |

Dette du §8 adressée à G6 : calculs dans les gabarits (`kit.html`, `offer_body.html`, `messages/row.html`,
`correct_panel.html`), découpage de `candidatures/dossier_web.py`, `stage_labels` posé deux fois
(`candidatures/web.py`, `messages/web.py`).

## Décisions métier (grill avec Nicolas, 07/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Frontière G6/G7 | G6 : parcours, ordre des zones, hiérarchie (bouton principal), textes et vocabulaire, états (vide, erreur, attente, succès), composants fonctionnels neutres avec les jetons CSS existants. G7 : couleurs, typographie, icônes, illustrations, animations, ton de l'assistant. |
| Q2 | Défauts A1–A9 | Corrigés dans G6, en premier bloc ; un test par défaut, qui échouait avant, et un test transversal sur l'héritage des cibles. |
| Q3 | Méthode | Le grill tranche les choix structurants ; un **artifact HTML commentable, avant le code**, tranche le détail (libellés, ordre, lexique) ; recette finale dans l'application. |
| Q4 | Prototype de Codex | Déposé par Nicolas dans `docs/procedures/g6-ux/` ; source d'inspiration de l'artifact. |
| Q5 | Dette du §8 | Traitée avec le fichier qu'on touche : `dossier_web.py` découpé par étape avec le parcours du dossier ; calculs des gabarits vers les `rules.py` ; `stage_labels` posé une fois. |
| Q6 | « Remplacer l'adresse » (H3 → G6) | Non codé : aucun lecteur ne produit ce cas ; au premier cas réel. |
| Q7 | Frappes perdues | `rocky.js` met la touche en attente pendant une requête HTMX et la rejoue une fois le fragment greffé ; abandonnée si la page change. |
| Q8 | Attente et succès | Bouton désactivé pendant sa requête et barre fine après 300 ms ; phrase d'attente à la place des gestes pour les appels longs (Gemini, PDF, import de CV) ; un seul composant de succès, annoncé aux lecteurs d'écran, avec « ↶ Annuler » quand le geste se défait. |
| Q9 | Motif | **Obligatoire pour toute décision**, « Plus tard » compris (jeu d'entraînement D14). |
| Q10 | Offres | Un seul panneau des motifs (tri, fiche, cockpit : mêmes touches, même question) ; fiche, filtres et position dans l'URL ; « Trier »/« Liste » gardent les filtres ; une décision depuis la fiche retire la ligne sur place et ouvre la suivante ; « ↶ Annuler » en Liste aussi ; trois décisions de même poids (un principal pousserait les étiquettes D14) : le principal est « Valider » une fois le panneau ouvert, « Trier les N offres » en Liste. |
| Q11 | Dossier, clics | « Valider la lettre » mène à l'Envoi ; PDF générés à l'arrivée sur l'Envoi si l'empreinte a changé (« Régénérer » seulement après un changement) ; « J'ai envoyé ma candidature » confirme avec des valeurs proposées (aujourd'hui, canal déduit de la source, dernières révisions), puis un récapitulatif modifiable et « ↶ Annuler » ; « CV prêt » reste un passage. Cible : **5 clics au plus sans Gemini** d'« À préparer » à « Envoyée ». |
| Q12 | Accord Gemini | **Par compte** : donné une fois, daté, journalisé, retirable dans Profil (Identité & préférences) ; un rappel « Gemini reçoit l'annonce et ta lettre » près du bouton. Ce qui part chez Gemini ne change pas (D4, Q15). Révise l'accord par geste de D3 et D4. |
| Q13 | Dossier, page | Gestes en fragments qui gardent la position et les plis ; étape et prochaine action une fois, dans l'en-tête ; Suivi : les 2 ou 3 étapes probables et « Autre étape… » ; « Préremplie » masquée tant que le préremplissage dort ; « Envoyée » depuis une candidature close ouvre le formulaire de confirmation. |
| Q14 | Messages | Principal : traiter « Ce qui a bougé », avec « Tout vu » ; boîtes réduites à une ligne d'état (connexion dans Système, et dans Messages seulement si une boîte est à reconnecter) ; 4 onglets (« À regarder », « À vérifier », « Retours d'employeurs », « Tous ») et un filtre ; « Corriger » avec « Fermer », un seul ouvert ; un geste ne relit que sa ligne. |
| Q15 | Profil | **4 sous-pages** avec adresse : Recherche (pistes, compétences) ; Parcours (expériences, projets, langues) ; Identité & préférences (accord Gemini) ; CV & kit. Libellés d'interface en français ; « Modifier » dans l'URL ; détails techniques de « Vérifier » derrière « Pourquoi ? ». |
| Q16 | Bilan | **Page de statistiques** : l'analyse des données métier en graphiques, comprise en quelques coups d'œil, sur une période et depuis le début ; chaque chiffre mène à sa liste filtrée. L'assistant peut la lire, jamais la créer. |
| Q17 | Système | **Page d'administration et de monitoring** : métriques visuelles, gestion des boîtes, coûts des modèles, état des modules, état de la veille et lancement manuel ; détails internes retirés ; « mis à jour à » ; seule la carte qui change se relit. Sous-page DevOps (VPS) après F2. |
| Q18 | Bilan, analyses | (1) Entonnoir : offres trouvées → examinées → Intéressé → dossiers → envoyées → réponse humaine → entretien → offre, taux par marche ; (2) rythme : envois et réponses humaines par semaine ou par mois, ligne de l'objectif ; (3) ce qui marche : par piste et par source (envois, réponses humaines, entretiens), délai médian de l'envoi à la première réponse humaine, score moyen avec et sans réponse ; (4) décisions : motifs les plus fréquents d'« Écarté » et d'« Intéressé », part sous le seuil. Sans nouvelle table ; définitions du cockpit. |
| Q19 | Bilan, périodes | 4 semaines · 3 mois · Depuis le début (par défaut) ; comparaison à la période précédente quand elle existe ; période dans l'URL. |
| Q20 | Système, portée | Les données du compte, et une partie « Application » (tous les comptes) visible des seuls comptes de `ROCKY_ADMIN_EMAILS`. À la bêta : page en administrateur seul, remplacée pour les autres par une page Système / Paramètres (plan §8). |
| Q21 | Système, métriques | Sous-pages Vue d'ensemble · Veille · Gmail · Modèles · Planification : pastille d'état par module avec sa raison ; offres trouvées et nouvelles par jour, grille source × jour par état, durée des veilles ; messages relevés par jour, relevés en échec, alertes par plateforme ; coût et appels par jour, par type et fournisseur, plafonds atteints ; prochains et derniers passages des tâches, par une **table des passages planifiés** (révise F1, Q8). « Lancer la veille » en tête. |
| Q22 | Assistant | Le tiroir ouvert sur le Bilan (ou le cockpit) reçoit les chiffres de la période affichée, par un cas d'usage de `candidatures` (mécanisme G4) ; il les cite, n'en calcule aucun. |
| Q23 | Découpage | Une étape, 8 blocs : 0 défauts · 1 coque · 2 Offres · 3 Candidatures · 4 Messages · 5 Profil · 6 Bilan · 7 Système. Recette initiale de Nicolas sur l'artifact juste avant le bloc 1 ; recette finale dans l'application après le bloc 7. |
| Q24 | Prototype de Codex | Versionné avec cette décision (données fictives, aucune donnée personnelle). |
| Q25 | Téléphone | Écrans utilisables à 390 px, contrôlés dans les essais ; pas de parcours propre au mobile. |
| Q26 | Critère de sortie | Les 8 points en tête de ce document. |
| Q27 | Artifact | Prototype **cliquable**, version propre de Claude en parallèle de celle de Codex (seules les idées de Codex jugées pertinentes reprises) : un onglet par écran, états clés basculables, parcours cibles jouables avec compteur de clics, onglet « Lexique », graphiques sur données fictives, niveaux de gris. |
| Q28 | Ordre | Cette décision ; bloc 0 codé et poussé seul ; artifact publié en parallèle ; bloc 1 une fois les commentaires de Nicolas repris ici. |

## Décisions techniques

### Bloc 0 — défauts A1–A9 (07/10)

| Défaut | Décision | Test (échouait avant) |
|---|---|---|
| A1 | `cards.html` : la relecture pendant une veille est demandée par un élément vide et caché (`hx-target="#cards"`), la parade du cockpit | `tests/system/test_inheritance.py` (toutes les pages de la navigation, au repos et pendant une veille et un relevé) |
| A2 | Tiroir : la lecture à l'ouverture passe par un enfant caché (`toggle[newState=='open'] from:#rocky-drawer`) ; le tiroir ne déclare plus de cible | `test_the_drawer_lends_no_target_to_the_links_it_shows` |
| A3 | `Action.leaves` (geste qui quitte Rocky) : formulaire non boosté pour « Connecter / Reconnecter une boîte Gmail » (cartes de Système, cockpit) ; `collect_now` répond la redirection à un formulaire boosté (`wants_fragment`) | `test_connecting_a_mailbox_leaves_rocky_without_boost`, `test_collecting_from_system_by_a_boosted_form_comes_back_to_system` |
| A4, A9 | Garantie centrale : `htmx-config` du gabarit fait afficher les réponses 4xx ; `shell.show_refusals` (intergiciel) change une réponse 4xx sans HTML (404 vide, JSON de FastAPI) adressée à HTMX en message dans `#erreur`, statut gardé ; `shell.refusal` pour un refus qui laisse le panneau ouvert (Messages). Les fragments HTML renvoyés en 4xx (Profil, lettre, import), muets jusqu'ici, s'affichent dans leur cible | `tests/system/test_errors.py` (offres, formulaire refusé, HTML gardé, sans HTMX), `test_a_gesture_refused_says_why` |
| A5 | Messages : pendant un relevé, seules les boîtes se relisent (`GET /messages/boites`, toutes les 3 s) ; à la fin, leur réponse émet `messages-changed` et le contenu se relit une fois. Révèle aussi que les onglets de Messages héritaient de `hx-swap="outerHTML"` pendant un relevé | `test_while_a_collection_runs_only_the_mailboxes_are_read_again` |
| A6 | « Valider cette lettre » refusée rend le formulaire tel que l'utilisateur l'a laissé ; « Adapter à l'annonce » emporte la lettre en cours (`hx-include`) et garde les paragraphes réécrits (`letter_view.written_over`), les autres prenant le texte proposé | `test_a_refused_validation_keeps_what_was_written`, `test_adapting_keeps_the_paragraphs_written_over` |
| A7 | Une candidature close jamais envoyée montre le formulaire de confirmation ; une candidature close déjà envoyée (`ApplicationFile.ever_sent`, `web_common.was_sent`, règle `sent_change`) est rouverte sans second envoi, et « Envoyée » ne lui est plus proposée dans le Suivi | `test_an_application_withdrawn_before_its_sending_can_still_be_sent`, `test_an_application_closed_after_its_sending_is_opened_again_without_a_second_sending` |
| A8 | `rocky.js` : une touche frappée pendant une requête HTMX attend et se rejoue après `htmx:afterSettle` (ou quand la réponse ne remplace rien, échoue ou expire) ; abandonnée après une navigation boostée | `tests/system/test_keys.py` : Chromium headless, page servie par le routage du navigateur, réponse retenue pendant la frappe de `i`, `1`, `Entrée` |

## Lexique

Arrêté à la recette de l'artifact.

## Essais et mesures

| Bloc | Vérification globale (`docker compose run --rm --build check`) | GitHub |
|---|---|---|
| 0 | 1 848 tests, verte : 122,7 s de pytest, 2 min 13 au total (charge moyenne 3 à 12) ; garde-fou 34 sur 34 | verte : pytest 114,5 s (passage `37604023405`) |

Bloc 0 : A3 (redirection vers Google) n'a pas été essayé dans un vrai navigateur : aucun client Google n'est
configuré sur l'instance d'essai ; il est couvert par les tests HTTP (formulaire non boosté, redirection 303).

## Recette

Artifact de la recette initiale (prototype cliquable, privé) : https://claude.ai/artifact/9982upNV24d21qd7Puk18N,
publié le 07/10 ; commentaires de Nicolas à reprendre ici avant le bloc 1.

### Recette initiale, premier retour de Nicolas (07/10)

| # | Retour | Décision |
|---|---|---|
| R1 | La maquette de Claude est austère ; celle de Codex est plus claire et plus attrayante, mais moins profonde | On garde la **profondeur** de la version de Claude (mécanismes, gestes, états, adresses, clavier, parcours) et la **présentation** de Codex pour ce qui s'affiche à l'écran (`docs/procedures/g6-ux/rocky-g6.html`). |
| R2 | 🔎 Offres | Présentation de Codex entière : recherche, pistes en puces, facettes, cartes d'opportunité, « Explorer » / « Mode focus », fiche et motifs en fenêtre, gestes « Ça m'intéresse », « Pas pour moi », « J'y reviens ». |
| R3 | 📬 Messages | Présentation de Codex entière : « Ce qui a bougé » en tête avec sa preuve dépliée, messages en cartes, onglets de Codex, correction en fenêtre, boîtes rangées en bas vers Système. |
| R4 | 👤 Profil & kit | Organisation visuelle de Codex (index des sections, une section à la fois), **« CV & kit » en premier** : compétences, expériences, projets et langues sont préremplis par la lecture du CV. On garde « Identité & préférences » avec l'accord pour l'IA, qui **nomme le modèle utilisé** (Gemini, GPT, Mistral ou Claude, selon la configuration). Révise Q15 (4 sous-pages) et Q12 (accord « Gemini » → accord pour l'IA). |
| R5 | ⚙️ Système | La version de Claude entière : Codex n'a pas la profondeur attendue. |
| R6 | 📝 Candidatures | Les onglets de Claude (À faire, À préparer, En préparation, Prêtes à envoyer, Envoyées, Closes) dans la présentation de Codex (tableau, dossier en panneaux numérotés, aperçu en document). | Point soumis à Nicolas dans l'artifact :

Version 2 de l'artifact publiée le 07/10 à la même adresse (présentation de Codex, profondeur de Claude).

| # | Point soumis | Décision de Nicolas (07/10) |
|---|---|---|
| R7 | « Ça m'intéresse » en bouton principal (Codex) ou trois décisions de même poids (Q10) | **Même poids, aucun bouton principal** : rien ne doit influencer le choix. Exception écrite au critère 2. |
| R8 | Lignes « à trancher » du lexique | On garde les premières versions : **« Offre »** (étape, catégorie de message), **« dossier »** (à côté de « candidature »), **« Juste »**. |

Version 3 publiée avec R7 et R8. Le lexique de l'artifact (onglet « Lexique ») est celui que le bloc 1 applique et
que le test du critère 5 garde.
en Tri, panneau fermé, aucun bouton principal (Q10) alors que le critère 2 en demande un par état (exception
proposée).

À venir : recette dans l'application (après le bloc 7).
