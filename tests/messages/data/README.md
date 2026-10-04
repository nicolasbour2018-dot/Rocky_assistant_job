# Jeux de données Gmail (E1, E2)

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

## Échantillon de l'archive A1 (E2)

Extraits de `backups/rocky-v1-20260924/exports/csv/` (archive A1, lecture seule) par un script jetable, le 04/10/2026.

| Fichier | Contenu |
|---|---|
| `archive_sample.csv` | 92 messages reçus du 21/08 au 24/09/2026 : retours d'employeurs, messages des plateformes, alertes, bruit, et les cas de l'ancien Rocky (Quora / French bee, METRO / Ministère de la justice, OVH et Google Agenda / Choisir le Service Public…). Colonnes : expéditeur, objet, extrait Gmail (l'archive n'a pas de corps), classement et rattachement de l'ancien Rocky (`v1_*`), **étiquettes** `category` et `application`, `note`, `checked` (vérifié par Nicolas) |
| `archive_applications.csv` | Les candidatures de l'archive (une par offre) : employeur, intitulé, étape traduite dans le nouveau Rocky, liens de l'offre sans paramètres |

Anonymisation : le nom et les adresses de Nicolas deviennent « Camille Martin » et `candidat@example.com` ; les
personnes nommées (recruteurs, réseau) deviennent « Recrutement » ou « Une personne » ; numéros de client, de colis et
noms de domaine personnels remplacés. Les employeurs restent : ils sont la matière du rattachement.
Étiquettes : proposées par l'agent, acceptées par Nicolas à la clôture d'E2 sans relecture ligne à ligne (`checked`
reste vide ; `oui` quand une ligne est relue). Une catégorie vide veut dire « À vérifier ».
