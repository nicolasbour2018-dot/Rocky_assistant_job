---
paths: rocky/offres/**
---

# Module `offres` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Écran : `docs/decisions/B4-coque-prototype.md` et `C7-ecran-offres.md`.

## Décisions et motifs (`decisions.py`, décision `docs/decisions/C7-ecran-offres.md`)
- Une décision **est** l'étiquette D14 (Q1) : codes anglais seulement (`rejected`, `too_senior`) ; libellés français
  uniquement à l'affichage. Un code publié ne se renomme plus (il casserait l'historique).
- Un motif au moins pour toute décision ; `other` exige une précision ; au plus 9 motifs (touches 1–9), plus `other`
  toujours dernier sur la touche `0`.
- `job_decisions` est en **ajout seul** : un changement est une nouvelle décision, « Annuler » une ligne `cancellation`
  qui vise une décision. La décision en vigueur se calcule (`effective_decisions`, `to_cancel`), jamais stockée.
- Une décision ne s'écrit que par `record_decision` / `cancel_last_decision`, avec son événement
  (`offres.decision_recorded`, `offres.decision_cancelled`) dans la même transaction, et une copie du score courant
  complet et de la piste affichée (Q11).
- Seul l'auteur `user` écrit en C7 ; « sous le seuil » n'est jamais une décision.

## Écran
- Le serveur rend chaque état en HTML ; HTMX place les fragments. Aucun état côté client.
- Seul JavaScript maison : `rocky/system/static/rocky.js` (raccourcis `data-key`). Toute nouvelle interaction passe
  par un attribut `hx-*` ou un élément HTML natif (`details`, `popover`, formulaire).
- Ce que montre l'écran se calcule dans `screen.py` (règles pures : file, filtres, carte) sur ce que `SqlStore` lit ;
  toute lecture passe par le compte (`offer_of`) : l'offre d'un autre compte répond 404.
- Une route qui ne vise qu'une offre (motifs, boutons, décision) ne charge pas toute la liste (mesure C7 : 520 offres,
  13 ms de lecture) ; seul l'écran qui l'affiche la lit.
- Chaque route répond aussi sans HTMX (page entière ou redirection).
- `hx-swap` et `hx-target` s'héritent des ancêtres : tout élément qui cible une zone déclare explicitement son
  `hx-swap` (bug « Revenir » de B4).

## Sources (`rocky/offres/sources/`, décision `docs/decisions/C1-sources.md`)
- **Ligne rouge (Q5)** : jamais de résolution ni d'esquive d'un défi anti-robot, de session ou compte réutilisé, de
  proxy, d'imitation d'empreinte TLS, de réessai. Un refus (403, 429, 999 de LinkedIn, défi Cloudflare, mur de
  connexion) lève `SourceRefusedError` et la source s'arrête pour la collecte. L'en-tête `x-datadome: protected` seul
  n'est **pas** un refus. Détail : un refus ou une réponse illisible arrête le détail de la source, un 404 non.
- Jamais de « 0 offre » silencieux : une page sans la structure attendue (aucune carte, clé de données absente) est
  une panne (`SourceFailedError`) ; seule une réponse vide ou une liste vide vaut « aucun résultat ».
- Toute requête passe par `PublicHttp` (pause par hôte, aucun réessai) ; aucun autre client HTTP. Un site qui refuse les
  rafales (429) reçoit une pause plus longue dans `HOST_PAUSE_SECONDS` (LinkedIn : 10 s, décision C1, Q7), jamais un
  réessai ni un autre moyen.
- Une source ne lève que `SourceRefusedError`, `SourceFailedError` ou `QuerySkippedError` ; tout le reste est un bug,
  isolé et journalisé par `collect`. Les raisons sont en français et ne citent jamais l'URL ni ses paramètres.
- Faits bruts de l'annonce seulement (textes contrat, télétravail, salaire) ; aucune interprétation (C3), aucune
  valeur devinée (un code inconnu reste vide). Une description partielle est gardée, marquée incomplète avec sa raison.
- Une source n'existe que par `registry.build_sources`. Nouveau connecteur : capture réelle
  (`docs/procedures/c1-captures/`), jeu anonymisé dans `tests/offres/sources/data/<source>/`, tests par `Replay`.

## Import par URL (`rocky/offres/imports/`, décision `docs/decisions/C2-import-url.md`)
- Un lien donne toujours un `ImportResult` : un aperçu, ou une issue (`invalid`, `refused`, `failed`) avec sa raison.
  Jamais d'exception avalée ni de lien ignoré en silence (fin de `_import_links`, E3 réutilise `import_link`).
- Un lien fourni par l'utilisateur ne se lit que par `PublicHttp.get_page` : hôte public vérifié à chaque
  redirection (anti-SSRF), page HTML, 3 Mo au plus. Un lien n'est jamais journalisé (il peut porter un jeton).
- Ordre de lecture : page à sections connue (`SECTIONED_PAGES` : Apec dessinée par le poste, E5) → JSON-LD
  `JobPosting` → conteneur connu → texte visible marqué incomplet. `estimatedSalary`
  n'est pas un fait de l'annonce ; aucun LLM avant C3.
- Une plateforme dont la fiche est vide pour un simple lecteur implémente `LinkSource` (Apec) ; sinon, page lue.
- Enrichir une offre : `enriched` (description remplacée seulement par une complète, faits connus jamais écrasés)
  ou `with_pasted_description` ; à l'écran, `enrich_offer` (collage, C7) et `enrich_offer_from_page` (lecture
  assistée, E5) recalculent le score aussitôt, gardent les pistes, ne touchent pas `last_seen_at` et écrivent
  `offres.offer_enriched` (`how`), jamais une adresse.
- Lecture assistée (décision `docs/decisions/E5-lecture-assistee.md`) : jamais dans la veille ni sans le geste de
  l'utilisateur ; la page affichée doit être sur le site de l'offre (`shows_the_offer`) ; un simple texte visible ne
  remplace pas la description (Q3). Une page dessinée par JavaScript se lit sur une capture faite par le poste
  (`docs/procedures/e5-captures/`), jamais sur une page inventée.
- Résumé : demandé par l'utilisateur, appelé hors de toute transaction, gardé dans `offer_summaries` avec l'empreinte
  de la description (`description_hash`) ; un résumé en échec n'est jamais gardé.
- Les jeux enregistrés viennent de `docs/procedures/c2-captures/` ; aucun nom de personne (recruteur, salarié).
- Écran : `wants_fragment` (de `system.shell`) décide fragment ou page entière ; la coque boost tous les liens.

## Analyse d'annonce (`rocky/offres/analysis/`, décision `docs/decisions/C3-analyse.md`)
- Tous les faits viennent de règles déterministes (`rules.py`, fonction pure) ; le LLM ne sert qu'au résumé, jamais
  à un fait ni au score. Toute règle modifiée change `RULES_VERSION`.
- Chaque fait garde sa phrase-preuve ; une valeur déduite le dit (`period_deduced`). Un code inconnu reste vide.
- Les faits d'une source se décodent par couple (source, valeur), jamais par la valeur seule.
- Compétences : termes du compte seulement (`account_skills`, sur le profil lu par `profil.web.profile_of`), jamais un
  dictionnaire global ni le SQL de `profil`.
- Changer une règle : relancer `docs/procedures/c3-mesure/measure.py` ; une baisse se justifie dans la décision.
  Une annotation ne se corrige que pour une erreur de lecture, notée dans le README de la mesure.

## Score (`rocky/offres/scoring/`, décisions `docs/decisions/C4-scoring.md` et `C5-calibrage.md`)
- `score` est une fonction pure : elle lit l'analyse C3, l'offre et `ScoringProfile`, n'écrit rien et ne relit jamais le
  texte. Le LLM n'intervient jamais dans le score.
- Un score par piste active ; chaque composante dit ce qu'elle a comparé (`detail`) et ses preuves. Une composante sans
  information garde `value=None`, jamais devinée (sa part dans le score : ci-dessous).
- Tous les paramètres (poids, points, plafond, seuil, confiance) sont des constantes de `model.py`, calibrées en C5 ;
  toute modification change `RULES_VERSION`. Les `features` ne contiennent que des valeurs JSON (D14).
- Le profil se lit par `profil.web.profile_of` (ou `stored_profile` hors requête) puis `scoring_profile`, jamais par le
  SQL de `profil`.
- Composante `value=None` : l'annonce ne dit rien → compte `ABSENT_VALUE` ; rien à comparer (aucune préférence, rien
  demandé, télétravail complet) → `neutral=True`, retirée. Tout nouveau cas `None` choisit explicitement l'un des deux.
- Une préférence personnelle va dans le profil (mots exclus, lieux, intitulés), jamais dans une règle (C5, Q22).
- Changer une règle : relancer `docs/procedures/c4-mesure/measure.py` et `docs/procedures/c5-calibrage/measure.py`
  (annotations aveugles et contrôle), et justifier l'écart dans la décision.
- `.score` est la pastille de note du prototype (hauteur fixe) : le détail du score utilise `.score-detail`.

## Offres enregistrées et veille (`rocky/offres/sql.py`, `usecases.py`, `watch/`, décision `docs/decisions/C6-veille.md`)
- Une offre ne s'écrit que par `record_offer`, dans **une** transaction avec ses pistes et ses scores courants ; aucune
  autre écriture de `job_offers`, `offer_tracks` ou `offer_scores`. Offre connue : `enriched`, jamais écrasée.
- Aucune offre n'est jetée : sous le seuil, elle est écrite, et son motif se calcule (`Score.threshold_reason`).
- Tout le SQL du module est dans `sql.py` (`SqlStore`, `SqlStorage`) ; le profil se lit par `profil.web.stored_profile`
  (hors requête) ou `profile_of`, jamais par le SQL de `profil`.
- Une veille est **toujours close** : `run_watch` ferme la veille dans un `finally` (`interrupted` sur une
  `BaseException`) ; `recover_interrupted` ferme au démarrage celles d'un processus tué. Aucune requête réseau dans une
  transaction. Veille et recalcul d'un compte passent par son verrou (`SqlStorage.lock`).
- Statut : seule la **recherche** d'une source compte (Q3) ; détail refusé et requête sautée sont signalés, jamais un
  échec ; une source en attente ou non configurée n'en est pas un.
- Un score stocké garde son `inputs_hash` (profil lu par le score + versions des règles) : ce qui change le score doit
  entrer dans `scoring_inputs`, sinon le recalcul (Q5) ne le verra pas.
- Invariant à garder vrai : `SqlStore.unscored_or_orphan_offers` est vide (critère de sortie de C6).
- La veille ne tourne jamais dans une requête HTTP : l'écran la confie au planificateur (`system.scheduler`).
