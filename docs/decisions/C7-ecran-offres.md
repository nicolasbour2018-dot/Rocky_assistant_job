# C7 — Écran Offres

Date : 29/09/2026 · Étape : C7 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q14) puis mode plan

Critère de sortie : « Tri de 20 offres au clavier ; chaque décision est tracée dans `events`. »

## Constats de départ

| Constat | Source |
|---|---|
| L'écran 🔎 Offres tourne sur le prototype B4 : 30 offres de l'archive en JSON, score provisoire, décisions en mémoire | `rocky/offres/prototype.py`, décision B4 |
| 517 offres réelles écrites par la veille avec leurs pistes et leurs scores courants ; 440 sous le seuil, 350 incomplètes | décision C6 (mesures) |
| Deux jeux de motifs : ceux de B4 (par décision) et ceux de l'annotation C5 (signés + ou −) | décisions B4 et C5 (Q9) |
| En C5, un Non signifie « je ne postulerais pas », souvent pour un motif bloquant, pas « hors profil » | décision C5 (rappel de Nicolas) |
| Une décision garde une copie du score affiché (étiquette D14) | décision C6 (Q6) |
| Geste « Enrichir » : moteur livré en C2 ; la lecture assistée demande une fenêtre sur le poste, que Docker n'ouvre pas | décisions C1 (Q6), C2 (Q4) |
| Le résumé Gemini n'est pas enregistré | plan §8 (C3 → C6, C7) |

## Décisions métier (grill avec Nicolas, 29/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Décision et étiquette | **Un seul geste** : la décision est l'étiquette D14. `interested` ≈ Oui, `rejected` ≈ Non ; `later` ne donne pas d'étiquette. |
| Q2 | Auteur | Seul `user` écrit en C7 ; la colonne `author` accepte `user`, `rule` et `ai` pour plus tard. « Sous le seuil » reste un indicateur calculé, jamais une décision. |
| Q3 | File de tri | Offres **sans décision, au-dessus du seuil**, par meilleur score décroissant ; une veille y insère les nouvelles à leur rang. « Plus tard » ne revient pas dans la file (filtre de la liste). Les offres sous le seuil restent hors de la file, derrière le compteur « N sous le seuil → ». |
| Q4 | Doublons entre sites | Chaque offre se décide séparément ; « vue aussi sur … » avec un lien vers l'autre offre dans la carte et la fiche. Aucune décision copiée. |
| Q5 | Enrichir | C7 livre **« Coller la description »** dans la fiche, avec recalcul du score. La lecture assistée (navigateur visible) est reportée : Playwright arrive en D2. |
| Q6 | Résumé | **À la demande** (bouton ou touche), enregistré et réaffiché ensuite, refait si la description change. |
| Q7 | Score d'une liste filtrée par piste | Le score **de cette piste** est affiché et sert au tri. La file et le seuil restent sur le meilleur score (C6). |
| Q8 | Annuler | `u` annule la dernière décision **en vigueur** du compte ; plusieurs `u` remontent l'historique, y compris après un rechargement ou le lendemain. Rien n'est supprimé : une ligne d'annulation et un événement s'ajoutent ; la décision précédente de l'offre revient, sinon l'offre repasse « à examiner ». Pour D14, seule la décision en vigueur de chaque offre compte ; annulations et changements restent lisibles. |
| Q9 | Sort des décisions de C7 | Un essai, sur le compte d'essai : Rocky repartira sur une **base neuve** après la bascule. Les décisions seront **exportées dans un fichier** avant, pour une analyse éventuelle (§8 → F2). |
| Q10 | Motifs | Tableau ci-dessous : les motifs de C5 les plus cités (séniorité, secteur, condition bloquante) entrent dans « Écarté » ; « trop junior » sort (« autre » le couvre) ; « autre » passe sur la touche `0`. Le signe de C5 est implicite (un motif d'« Intéressé » attire, un motif d'« Écarté » rebute). |
| Q11 | Piste de l'étiquette | La décision garde le **score complet** (toutes les pistes, `Score.to_json`), `rules_version`, `inputs_hash`, la **piste dont le score était affiché** (la meilleure en tri, la piste filtrée dans la liste) et le score entier affiché. |
| Q12 | Carte et fiche | De haut en bas : intitulé, employeur, lieu, score et confiance → pastilles (pistes, source et ancienneté, date limite, incomplète, vue aussi sur, plafond) → synthèse (éliminatoires, compétences ✔ prouvées par une expérience ou un projet / ≈ déclarées, manques) → faits (contrat, salaire ou TJM avec sa période, télétravail, expérience demandée) → boutons de décision → résumé → « Pourquoi ce score ? » replié → description mise en forme, repliée → lien d'origine. |
| Q13 | Incomplètes | Filtres **indépendants** : « Incomplètes » montre toutes les offres incomplètes, au-dessus et au-dessous du seuil ; « Sous le seuil » ajoute les offres sous le seuil. Dans la fiche d'une offre incomplète, « Coller la description » recalcule aussitôt le score ; l'offre reste à l'écran. Pas de mode d'enrichissement séparé. |
| Q14 | Suppression d'une piste | Hors C7 : bouton inchangé, constat renvoyé à `profil` (§8). |

### Motifs (codes stockés → libellés affichés ; touche = rang, `0` = autre)

| Décision | Motifs |
|---|---|
| `interested` — Intéressé | `target_job` métier visé · `skills_match` compétences alignées · `company_appeal` entreprise ou secteur attirant · `location` lieu ou télétravail · `salary` salaire · `growth` évolution ou apprentissage · `other` autre |
| `rejected` — Écarté | `not_the_job` pas le métier · `too_senior` trop senior · `missing_skills` compétences manquantes · `sector` secteur ou domaine · `company` entreprise · `location` lieu ou télétravail · `contract` contrat · `salary` salaire · `blocking_condition` condition bloquante (visa, langue, permis, habilitation) · `other` autre |
| `later` — Plus tard | `reread` à relire à tête reposée · `missing_info` infos manquantes · `application_to_prepare` candidature à préparer · `distant_deadline` date limite lointaine · `other` autre |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Décisions | `job_decisions` en **ajout seul** (migration `0005`) : une ligne `decision` (valeur, motifs, précision, auteur, piste affichée, score entier affiché, copie `Score.to_json`, `rules_version`, `inputs_hash`) ou `cancellation` (`cancels_id`, unique). Contraintes : une décision a une valeur et un score, une annulation a une cible, une décision ne s'annule qu'une fois | D14 et Q8 : l'historique complet reste lisible ; la base refuse une ligne incohérente. |
| Décision en vigueur | Calculée par `effective_decisions` / `to_cancel` (`decisions.py`, fonctions pures) : la dernière décision non annulée de l'offre ; « Annuler » vise la dernière décision non annulée du compte | Plan §3 (indicateurs calculés) ; une seule règle pour la liste, la file et l'annulation. |
| Journal | `offres.decision_recorded` (valeur, motifs, précision, piste, score, `rules_version`, valeur précédente), `offres.decision_cancelled` (valeur annulée, valeur rendue), `offres.offer_enriched` (score avant, après) ; dans la transaction de l'écriture | Critère de sortie : chaque décision est tracée dans `events`. |
| Résumé | `offer_summaries` (une ligne par offre, remplacée) avec `description_hash` ; appel au modèle **hors transaction** ; un échec n'est pas gardé | Q6 ; règle C6 : aucune requête réseau dans une transaction. |
| Coller une description | `enrich_offer` : `with_pasted_description`, `update(seen=False)` (la date de dernière vue reste celle de la source), recalcul et remplacement des scores, pistes inchangées | Q5, Q13 ; même unité que `record_offer`. |
| Lecture de l'écran | `SqlStore.listed_offers` lit les offres du compte, leurs rattachements et leurs scores courants (trois requêtes, sans la colonne `detail`) ; filtres, tri, file et pages se calculent dans `screen.py` (fonctions pures). **Écart au plan** (qui prévoyait une requête jointe par filtre) : une seule règle testée sans base, 13 ms pour 520 offres | AGENTS §4 : règles pures → SQL du module. À revoir si un compte dépasse quelques milliers d'offres. |
| Routes légères | Motifs, boutons et validation d'une décision ne lisent que l'offre visée (`offer_of`, décisions de l'offre) ; seul l'écran qui affiche la liste la charge | Mesure ci-dessous : motifs 21 → 8 ms, décision 59 → 44 ms. |
| Pages | 100 lignes, « Afficher plus » ajoute les suivantes (`hx-swap="outerHTML"` sur la ligne du bouton) | 517 offres réelles. |
| Carte | `OfferCard` (`screen.py`) : score de la piste affichée, analyse recalculée (C6) pour les faits, compétences ✔ prouvées / ≈ déclarées d'après `ScoringProfile`, éliminatoires = plafonds du score (conditions bloquantes, mots exclus, étranger), manques = `gaps` | Q12 ; les conditions bloquantes sont déjà des plafonds (C4), rien n'est compté deux fois. |
| « Pourquoi ? » | `import_score.html` réutilisé pour la piste affichée (`score_track`) | Pas de copie du tableau des composantes. |
| Touches | `0` autre, `r` résumer, `c` coller la description ; les autres de B4 inchangées | Q10, Q6, Q13. |
| Frappes perdues | **Écart au plan** : pas de `hx-sync`. Il met des requêtes en file, mais une touche frappée avant qu'HTMX ait branché le fragment arrivé (20 ms) ne déclenche aucune requête. Constat B4 → C7 laissé ouvert pour le VPS | Mesure ci-dessous. |
| Prototype | `prototype.py`, `prototype_offers.json`, `tests/offres/test_prototype.py` et `docs/procedures/b4-prototype/` supprimés (grille d'essai de B4 dans l'historique Git) | Constat B4 → C7. |

## Mesures (29/09/2026)

| Contrôle | Résultat |
|---|---|
| Tests automatiques | Règles des décisions et de l'écran (`test_decisions.py`, `test_screen.py`), cas d'usage sur PostgreSQL (`test_decision_usecases.py` : décision et événement dans la même transaction, annulation, ajout seul garanti par la base, collage, résumé périmé), écran par HTTP (`test_web.py`, 29 tests sur offres semées par `record_offer`) |
| Tri au clavier, Chromium (Playwright, instance à part : schéma jetable de `test-db`, 24 offres semées, faux modèle de langage) | **20 offres triées au clavier** (`e` → `2` `4` → `Entrée`, `i` → `1`, `p` → `0` → `t` précision → `Échap` → `Entrée`), compteur à jour à chaque décision ; `u` deux fois rend les deux dernières offres dans l'ordre ; `w`, `r`, `j`, `k` répondent ; file vidée → « Tout est trié », puis `u` rend l'offre |
| Frappes trop rapides | Un robot qui frappe dans la milliseconde qui suit l'arrivée d'un fragment perd la touche, ou fait partir le formulaire sans HTMX (page rechargée, décision enregistrée quand même). Avec 80 ms entre deux touches (rythme humain rapide), aucune perte sur 25 décisions. Une navigation complète comptée une fois pendant une série, non reproduite ensuite touche par touche |
| Temps de réponse, 520 offres (TestClient, base `test-db`, poste) | Carte de tri : médiane 33 ms (max 110) ; motifs 8 ms (15) ; décision 44 ms (87) ; liste 22 ms (55) ; fiche 33 ms (67). Parts : session 8 ms, lecture de la liste 13 ms, profil 5 ms, analyse d'une offre 0,2 ms. Critère B4 (< 150 ms en local) tenu |
