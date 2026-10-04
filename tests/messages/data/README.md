# Jeux de données Gmail (E1)

Réponses **reconstruites** au format de l'API Gmail v1 et d'OAuth Google (`format=full`, corps en base64url, en-têtes
décodés), d'après la documentation publique. Aucune n'est une capture d'une vraie boîte : personnes, adresses,
employeurs et liens sont fictifs (`example.com`, `exemple-conseil.fr`, `societe-fictive.fr`). Aucun jeton réel.

| Fichier | Contenu | Ce qu'il éprouve |
|---|---|---|
| `message_reply.json` | Réponse d'un recruteur, `multipart/alternative` (texte + HTML) | En-têtes, extrait, corps, fil, identifiant RFC |
| `message_alert_html_only.json` | Alerte Indeed en HTML seul, catégorie Promotions | Texte déduit du HTML (sans `script` ni `style`), entités de l'extrait |
| `message_latin1_attachment.json` | Texte en ISO-8859-1 + pièce jointe PDF, copie à un tiers | Jeu de caractères, nom de la pièce jointe sans son contenu, destinataires |
| `list_page_1.json`, `list_page_2.json` | `users.messages.list` en deux pages (`nextPageToken`) | Pagination |
| `list_empty.json` | `users.messages.list` sans résultat (pas de clé `messages`) | Liste vide |
| `profile.json` | `users.getProfile` | Adresse de la boîte lue chez Google |
| `oauth_exchange.json`, `oauth_refresh.json` | Réponses du point de jeton (code échangé, accès rafraîchi) | Jeton de rafraîchissement, scope accordé |
| `oauth_invalid_grant.json` | Refus `invalid_grant` | Boîte « À reconnecter » |

Les noms évitent `token*.json`, réservé aux secrets par le garde-fou (`AGENTS.md`, §3).
Générés une fois par un script jetable ; à remplacer par des captures anonymisées si une réponse réelle diffère.
