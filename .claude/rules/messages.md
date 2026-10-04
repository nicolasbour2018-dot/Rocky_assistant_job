---
paths: rocky/messages/**
---

# Module `messages` — règles propres

Complète `AGENTS.md` ; ne répète pas ce qui s'y trouve. Décision : `docs/decisions/E1-collecte.md`.

## Collecte (E1)
- **Enregistrer avant de décider** : un message entre en base par `SqlStore.add_message` (seul, dans sa transaction,
  `ON CONFLICT DO NOTHING`), puis seulement ses identifiants partent au crochet `app.state.messages_collected`, après la
  validation. Toute décision sur un message (E2, E4) part de ce crochet ou d'une ligne `email_messages`, avec une clé
  étrangère `NOT NULL` vers `email_messages.id`. Une ligne de `email_messages` n'est jamais modifiée.
- Un identifiant Gmail déjà en base n'est **jamais retéléchargé** (`known_ids` avant tout `get`).
- Une collecte est toujours close (`_close` dans `finally`) ; la fenêtre ne part que d'une collecte **terminée**.
- Changer une requête (`rules.QUERIES`, `ALERT_DOMAINS`) change `QUERIES_VERSION`.

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
