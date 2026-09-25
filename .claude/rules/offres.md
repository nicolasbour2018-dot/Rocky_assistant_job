---
paths: rocky/offres/**
---

# Module `offres` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Décisions : `docs/decisions/B4-coque-prototype.md`.

## Ce qui est gardé, ce qui est jetable (prototype B4)
- **Gardés pour C7** : `decisions.py` (valeurs, motifs, règles), `web.py`, `templates/offres/`.
- **Jetables, supprimés en C7** : `prototype.py`, `prototype_offers.json` (et la procédure
  `docs/procedures/b4-prototype/`). Aucun autre fichier n'importe `prototype.py` hors de `web.py`.
- Les scores de `prototype_offers.json` sont une maquette : ne jamais s'en servir comme base du scoring C4.

## Décisions et motifs
- Données : codes anglais seulement (`rejected`, `too_senior`) ; libellés français uniquement à l'affichage.
- Un motif au moins pour toute décision ; `other` exige une précision ; au plus 9 motifs par décision (touches 1–9).

## Écran
- Le serveur rend chaque état en HTML ; HTMX place les fragments. Aucun état côté client.
- Seul JavaScript maison : `rocky/system/static/rocky.js` (raccourcis `data-key`). Toute nouvelle interaction passe
  par un attribut `hx-*` ou un élément HTML natif (`details`, `popover`, formulaire).
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
- Toute requête passe par `PublicHttp` (pause par hôte, aucun réessai) ; aucun autre client HTTP.
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
- Ordre de lecture : JSON-LD `JobPosting` → conteneur connu → texte visible marqué incomplet. `estimatedSalary`
  n'est pas un fait de l'annonce ; aucun LLM avant C3.
- Une plateforme dont la fiche est vide pour un simple lecteur implémente `LinkSource` (Apec) ; sinon, page lue.
- Enrichir une offre : `enriched` (description remplacée seulement par une complète, faits connus jamais écrasés)
  ou `with_pasted_description`.
- Les jeux enregistrés viennent de `docs/procedures/c2-captures/` ; aucun nom de personne (recruteur, salarié).
- Écran : `wants_fragment` (de `system.shell`) décide fragment ou page entière ; la coque boost tous les liens.

## Analyse d'annonce (`rocky/offres/analysis/`, décision `docs/decisions/C3-analyse.md`)
- Tous les faits viennent de règles déterministes (`rules.py`, fonction pure) ; le LLM ne sert qu'au résumé, jamais
  à un fait ni au score. Toute règle modifiée change `RULES_VERSION`.
- Chaque fait garde sa phrase-preuve ; une valeur déduite le dit (`period_deduced`). Un code inconnu reste vide.
- Les faits d'une source se décodent par couple (source, valeur), jamais par la valeur seule.
- Compétences : termes du compte seulement (`account_skills`, lues par `profil.web.skills_of`), jamais un
  dictionnaire global ni le SQL de `profil`.
- Changer une règle : relancer `docs/procedures/c3-mesure/measure.py` ; une baisse se justifie dans la décision.
  Une annotation ne se corrige que pour une erreur de lecture, notée dans le README de la mesure.
