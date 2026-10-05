# E3 — Captures des alertes emploi

Décision : `docs/decisions/E3-alertes.md`. Chaque lecteur d'alerte s'écrit sur une **vraie alerte** (Q6), anonymisée
avant d'entrer dans le dépôt (`tests/messages/data/alerts/`, provenance dans `tests/messages/data/README.md`).

## 1. Exporter les alertes (lecture seule, hors du dépôt)

Les messages dont la décision en vigueur est « Alerte emploi », dans un fichier du dossier temporaire de la session
(données personnelles : **jamais** dans le dépôt) :

```sh
docker compose exec -T db psql -U rocky_admin -d rocky -At -c "BEGIN READ ONLY;
WITH cur AS (SELECT DISTINCT ON (message_id) message_id, category FROM message_decisions
             ORDER BY message_id, id DESC)
SELECT json_build_object('id', m.id, 'sender', m.sender, 'address', m.sender_address, 'subject', m.subject,
       'received_at', m.received_at, 'body_text', m.body_text, 'body_html', m.body_html)
FROM email_messages m JOIN cur ON cur.message_id = m.id
WHERE cur.category = 'job_alert' ORDER BY m.received_at DESC; ROLLBACK;" \
  | grep -v '^BEGIN$\|^ROLLBACK$' > <dossier temporaire>/alerts.jsonl
```

## 2. Anonymiser une alerte par forme

```sh
uv run python docs/procedures/e3-captures/anonymize_alerts.py <dossier temporaire>/alerts.jsonl \
  tests/messages/data/alerts <adresse>:<rang>:<nom> ...
```

`rang` : rang de l'alerte parmi celles de l'adresse, la plus récente d'abord. Relire ensuite le fichier : aucun nom,
aucune adresse, aucun jeton (`grep -il "<prénom>\|<nom>\|stlt=[A-Za-z0-9]\{20\}"` ne doit rien trouver).

## 3. Écrire ou corriger un lecteur

Lecteurs dans `rocky/messages/alerts/rules.py` (`READERS`, par adresse exacte) ; tests dans
`tests/messages/test_alerts_rules.py`. Tout changement d'un lecteur change `ALERTS_VERSION`.
Mesure sur toutes les alertes exportées : cartes lues par plateforme, champs remplis, alertes sans carte.
