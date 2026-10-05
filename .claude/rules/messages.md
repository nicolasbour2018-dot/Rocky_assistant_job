---
paths: rocky/messages/**
---

# Module `messages` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Décisions : `docs/decisions/E1-collecte.md`,
`docs/decisions/E2-classification.md`, `docs/decisions/E4-decisions-ecran.md`, `docs/decisions/E3-alertes.md`.

## Collecte (E1)
- **Enregistrer avant de décider** : un message entre en base par `SqlStore.add_message` (seul, dans sa transaction,
  `ON CONFLICT DO NOTHING`), puis seulement ses identifiants partent au crochet `app.state.messages_collected`, après la
  validation. Toute décision sur un message (E2, E4) part de ce crochet ou d'une ligne `email_messages`, avec une clé
  étrangère `NOT NULL` vers `email_messages.id`. Une ligne de `email_messages` n'est jamais modifiée.
- Un identifiant Gmail déjà en base n'est **jamais retéléchargé** (`known_ids` avant tout `get`).
- Une collecte est toujours close (`_close` dans `finally`) ; la fenêtre ne part que d'une collecte **terminée**.
- Changer une requête (`rules.QUERIES`, `ALERT_DOMAINS`) change `QUERIES_VERSION`.

## Classification (E2)
- Deux axes : la **catégorie** (phrases, formes d'objet des plateformes, modèle) et la **candidature** (fil, domaine
  enregistrable, nom entier, intitulé). Toute comparaison se fait en forme pliée (`offres.analysis.text.fold`) et en
  **mots entiers** ; jamais de sous-chaîne d'un nom dans une adresse.
- Une décision s'ajoute (`message_decisions`), la dernière est en vigueur ; le schéma refuse une décision sans règle,
  extrait et preuve. Une décision s'écrit seule dans sa transaction, avec son événement `messages.message_classified`.
- Le modèle ne voit qu'un message `Pending` (signal de recherche, règles muettes ou contradictoires), sous les plafonds
  du compte, jamais dans une transaction ; sa citation est vérifiée dans le message ; un échec n'écrit aucune décision.
- Changer une liste, une phrase, une forme d'objet ou les consignes du modèle change `CLASSIFY_VERSION`, et s'éprouve
  sur `tests/messages/test_classification_archive.py` (aucun rattachement faux de confiance moyenne ou haute).
- Les tests n'appellent jamais Gemini : `ScriptedModel` (`tests/messages/fakes.py`).

## Décisions et transitions (E4)
- Une décision suit dans **sa** transaction : `SqlStore.follow` → `decisions.usecases.follow_decision` (crochet donné à
  `SqlStorage` par `MessagesService`). Une transition appliquée, son changement d'étape et leurs événements sont validés
  avec la décision, ou rien.
- `messages` n'écrit chez `candidatures` et `offres` que par leurs fonctions publiques sur la connexion en cours
  (`messages/links.py`), jamais par leur SQL.
- « Ce qui a bougé » = `mail_transitions` sans ligne de `mail_transition_settlements` : rien n'en sort sans geste ; tout
  est en ajout seul. Un nouveau type d'écriture dans un cas d'usage s'ajoute aux points de panne de
  `test_decisions_usecases.py`.
- Une décision `user` garde la décision qu'elle revoit (`reviews_id`) et ne déclenche jamais de transition
  automatique : elle la propose.
- Les règles par compte (`mail_sender_rules`) ne visent que les catégories sans candidature, jamais un relais, une
  adresse d'alerte ni un ATS (`decisions.rules.rule_possible`).
- Un geste de l'écran répond par `content.html` (vue de `HX-Current-URL`) avec le compteur de 📬 hors bande.

## Alertes comme source (E3)
- Une alerte = un message dont la décision en vigueur est `job_alert`, lu **une fois** (`alert_readings`,
  `UNIQUE(message_id)`). Le lecteur se choisit par **adresse exacte** (`alerts.rules.READERS`) et s'écrit sur une vraie
  alerte anonymisée (`docs/procedures/e3-captures/`) ; changer un lecteur change `ALERTS_VERSION`.
- **Chaque carte donne une offre** (`offres.web.record_alert_offer`, origine `alert`, meilleure piste) ; identité
  stable d'une alerte à l'autre (numéro de la plateforme, sinon `card_key`), jamais le lien de suivi.
- **Limite (Q8)** : au plus `ALERTS_PER_DAY` (10) alertes donnent leurs offres par jour de Paris, les plus récentes
  d'abord ; les autres attendent. Une alerte de plus de `ALERT_MAX_AGE` (3 jours) ne donne rien (lecture `too_old`).
- Fiche lue **hors transaction** par `import_link` (fabrique `offres.imports.web.posting_pages`) ; jamais pour une offre
  connue complète ni une plateforme qui a refusé pendant le passage (règle d'arrêt C1).
  Chaque fiche non lue garde sa raison (`alert_offers`) ; un lien n'est jamais journalisé ni mis dans un événement.
- Une alerte s'écrit **en une transaction** (lecture, offres, lignes, `messages.alert_read`), sous le verrou des offres
  du compte essayé en mode transaction : veille en cours → rien d'écrit, alerte reprise. Une panne de lecture (lecteur,
  fiche) rend la lecture `failed` ; une panne de la base remonte et rien n'est écrit. Un nouveau type d'écriture
  s'ajoute aux points de panne de `test_alerts_usecases.py`.

## Google
- Scope unique `gmail.readonly` (`oauth.SCOPE`) : aucun autre, jamais d'écriture dans Gmail (AGENTS §6).
- Tout appel passe par `oauth.google_json` : délai borné, aucun réessai, `GmailError` avec une raison en français. Un
  jeton, un code ou le secret du client n'apparaît jamais dans une raison, un journal ou un événement ; une raison de
  Google n'est reprise que par son code court (`accessNotConfigured`), jamais par son texte libre.
- Le jeton de rafraîchissement n'est stocké que scellé (`TokenCipher`, `ROCKY_SECRET_KEY`).
- Aucun appel réseau dans une transaction ; dans une requête web, seul le retour de Google (échange du code) appelle
  Google. Une collecte tourne dans le fil du planificateur.

## Tests
- Réponses de Google reconstruites dans `tests/messages/data/` (provenance dans son `README.md`) ; noms en
  `oauth_*.json`, jamais `token*.json` (réservé aux secrets par le garde-fou).
- Faux adaptateurs : `tests/messages/fakes.py` (`FakeGmail`, `FakeReader`, `Google` pour `httpx2.MockTransport`).
- Les verrous consultatifs sont partagés par toute la base : leur clé inclut `current_schema()` (un schéma par worker
  de test).
