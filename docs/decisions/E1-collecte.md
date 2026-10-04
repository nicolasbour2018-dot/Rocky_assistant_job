# E1 — Collecte des messages

Date : 04/10/2026 · Étape : E1 (plan v2) · Préparation : mode plan, questions à Nicolas (Q1–Q8)

Critère de sortie (plan) : « Une resynchronisation ne retraite rien ; aucun statut ne change sans message enregistré ».

## Constats de départ

| Constat | Source |
|---|---|
| La classification et le tri (import des liens compris) tournent **avant** l'enregistrement du message | `dashboard/rocky/gmail_service.py` (l. 827-865), historique ; plan §6 « Statut Gmail changé avant l'enregistrement du message » |
| Requête sans filtre de catégorie : `newer_than:180d`, une seule page de 100 messages ; toute la fenêtre est relue à chaque passage | `gmail_service.py` (l. 787-790) ; plan §6 « Requête Gmail non filtrée » |
| Jeton OAuth en clair dans un fichier par boîte ; client « Desktop » ; retour vers Streamlit (`localhost:8501`) | `gmail_service.py` (l. 404-635), `dashboard/rocky/config.py` |
| Le corps n'était pas stocké : impossible de justifier une décision après coup | `database/schema.sql` (`email_messages`) |
| Aucune bibliothèque Google dans le nouveau Rocky ; les API externes passent par `httpx2` (délai borné, raison en français) | `rocky/system/llm.py`, `rocky/offres/sources/france_travail.py` |
| Aucun secret n'est gardé en base : les jetons de Rocky n'y sont qu'en empreinte | `rocky/system/auth/sql.py` (`token_hash`) |
| 📬 Messages est une page vide ; `messages` est déjà un module connu du journal | `rocky/system/shell.py`, `rocky/system/events.py` (`MODULES`) |
| Vérification globale à 1 min 47 – 1 min 58 pour une limite de 2 min | plan §8 (D5 → B1) |

## Décisions métier (Nicolas, 04/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Durée de la vérification | Tests en parallèle (`pytest-xdist`, `pytest -n auto` dans `check`), avant le code d'E1. |
| Q2 | Branchement d'une boîte | Bouton **« Connecter une boîte Gmail »** dans Rocky : Google demande l'accord, puis revient sur `/messages/gmail/retour` (adresse construite depuis `ROCKY_PUBLIC_URL`). Client Google « Application Web » créé par Nicolas (`docs/procedures/e1-gmail/`). Scope `gmail.readonly` seul. **Plusieurs boîtes** par compte. |
| Q3 | Jeton de rafraîchissement | **Chiffré en base** avec la clé `ROCKY_SECRET_KEY`. Sans client Google ou sans clé : « Gmail n'est pas configuré ». |
| Q4 | Requêtes | **Deux requêtes**, dédupliquées : *retours* (`-category:promotions -category:social -category:forums`) et *alertes* (expéditeurs des plateformes d'alertes, quelle que soit la catégorie). |
| Q5 | Contenu gardé | En-têtes (expéditeur, destinataires, objet, date, identifiant RFC), extrait, **corps texte et HTML** (plafonnés, marqués tronqués), libellés Gmail, fil, noms des pièces jointes (jamais leur contenu). |
| Q6 | Historique | Première collecte d'une boîte : **30 jours**. Ensuite : depuis le début de la dernière collecte **terminée**, moins un jour de marge. |
| Q7 | Rythme | **Toutes les heures** par le planificateur (D12), plus « Relever maintenant ». Une collecte est toujours close : terminée, partielle, échouée ou interrompue. |
| Q8 | Écran | 📬 Messages : les boîtes (connecter, déconnecter, état, dernière collecte, raison d'un échec, « Reconnecter » si Google a retiré l'accès), « Relever maintenant », la liste brute des derniers messages (date, boîte, expéditeur, objet, requête d'origine), **sans décision** (E2, E4). |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Accès à Google | REST Gmail et OAuth par `httpx2` (`rocky/messages/gmail.py`, `oauth.py`) : délai de 30 s, aucun réessai, toute panne devient une `GmailError` avec sa raison en français ; ni jeton ni code dans une raison, une URL journalisée ou un événement | Même forme que `system/llm.py` ; pas de `google-api-python-client` (lourd, non typé) pour 6 appels |
| Dépendances | `cryptography` (Fernet, Q3) ; `pytest-xdist` en dev (Q1) | Chiffrement authentifié standard ; xdist : la seule voie mesurée sous 2 min sans retoucher les tests |
| Clé | `ROCKY_SECRET_KEY` : clé Fernet (procédure : `Fernet.generate_key()`). Absente → Gmail « non configuré » ; présente mais invalide → l'application refuse de démarrer (`ConfigError`) | Une clé fausse ne doit pas faire croire à des boîtes perdues |
| OAuth | Code d'autorisation + **PKCE** (`S256`), `state` aléatoire, `access_type=offline`, `prompt=select_account consent` (choix du compte, donc d'une autre boîte ; Google redonne toujours un jeton de rafraîchissement). `state`, vérificateur et compte voyagent dans un cookie `HttpOnly`, `SameSite=Lax`, chiffré, valable 15 min, effacé au retour. Un accord sans `gmail.readonly` (case décochée) est refusé avec sa raison | Pas de table pour un état de 15 min ; `SameSite=Lax` laisse passer le retour de Google (navigation de premier niveau) |
| Adresse de la boîte | Lue chez Google (`users/me/profile`) après l'accord, jamais saisie. Une boîte déjà connue du compte est **reconnectée** (jeton remplacé), pas dupliquée | L'ancien Rocky vérifiait déjà que le jeton était celui de la boîte |
| Déconnexion | Révoque le jeton chez Google, l'efface ; la boîte et ses messages restent (données du compte, futures preuves). Une révocation refusée par Google n'empêche pas l'effacement local, elle est signalée | L'utilisateur garde la main sur l'accès, sans perdre l'historique |
| Accès retiré | `invalid_grant` au rafraîchissement → boîte « À reconnecter » (événement `messages.mailbox_access_lost`), collecte échouée avec sa raison | Le mode « Test » de Google retire l'accès au bout de 7 jours : l'écran doit le dire |
| Requête *alertes* | `from:(indeed.com OR apec.fr OR linkedin.com OR welcometothejungle.com OR hellowork.com OR cadremploi.fr)` ; *retours* : la requête de Q4. Les deux excluent `in:sent`, `in:drafts`, `in:chats` ; spam et corbeille sont exclus par Gmail. Fenêtre : `after:<secondes>`. Constantes versionnées `QUERIES_VERSION`, gardée avec chaque message et chaque collecte | Plateformes d'E3 ; seuls les messages reçus comptent ; un changement de requête se lit dans les données (D14) |
| Idempotence | Les identifiants des deux requêtes sont listés (toutes les pages), ceux déjà en base sont retirés **sans être téléchargés**, les autres sont lus (`format=full`) puis insérés avec `ON CONFLICT (mailbox_id, gmail_id) DO NOTHING`. `found_by` garde les requêtes qui ont trouvé le message. Un message en base n'est jamais modifié | « Une resynchronisation ne retraite rien » devient mesurable : zéro téléchargement, zéro insertion |
| Un message par transaction | Chaque message est écrit seul ; un message illisible ou une panne de lecture n'arrête pas les autres : la collecte est **partielle**, avec le nombre de messages non écrits. La fenêtre suivante part de la dernière collecte terminée, donc ils sont repris ; elle ne remonte jamais au-delà de 30 jours | Aucune perte silencieuse ; la fenêtre ne grandit pas sans fin si un message reste illisible |
| Avant toute décision | E1 ne décide rien. Le seul point d'entrée des décisions (E2, E4) est le crochet `app.state.messages_collected(account_id, message_ids)`, appelé **après la validation**, avec les seuls messages réellement insérés ; une resynchronisation l'appelle avec une liste vide. Les tables de décision auront une clé étrangère `NOT NULL` vers `email_messages.id` | Le critère « aucun statut ne change sans message enregistré » est porté par le schéma et par l'ordre des opérations |
| Collectes | Table `mail_syncs` (une ligne par boîte et par collecte : déclencheur, statut, fenêtre, compteurs listés / nouveaux / déjà connus / non écrits, raison). Verrou consultatif par boîte, de clé `hashtext(nom || current_schema())` (les verrous sont communs à toute la base, et chaque worker de test a son schéma) : deux collectes de la même boîte ne se chevauchent pas. Au démarrage, une collecte restée « en cours » est close « interrompue » | Même mécanique que la veille (`watch_runs`, `recover_interrupted`, C6) |
| Journal | `messages.mailbox_connected`, `mailbox_reconnected`, `mailbox_disconnected` (auteur `user`), `mailbox_access_lost`, `sync_finished`, `sync_interrupted` (auteur `system`, ou `user` pour « Relever maintenant »). Aucun événement par message : la ligne du message est le fait | Le journal trace décisions et transitions ; un message reçu n'en est pas une |
| Corps | Texte et HTML plafonnés chacun à 500 000 caractères (`truncated`) ; texte déduit du HTML quand le message n'a pas de partie texte | Assez pour les preuves (E2) et les liens (E3) ; une lettre d'information géante ne remplit pas la base |
| Planificateur | Tâche périodique `messages` toutes les heures (première au démarrage) : chaque boîte connectée d'un compte actif, l'une après l'autre. « Relever maintenant » soumet une tâche ponctuelle du compte ; l'écran suit la collecte en interrogeant un fragment | Le planificateur reste le seul déclencheur (D12) ; jamais de réseau dans une requête web |
| Commande | `rocky-admin messages <email>` : une collecte réelle des boîtes du compte, compte rendu à l'écran (réseau réel : avec l'accord de Nicolas) | Diagnostic sans navigateur, comme `rocky-admin veille` |
| Tests | Règles pures sans base ; cas d'usage et service sur PostgreSQL avec un faux Gmail (`FakeGmail`), comme la veille (C6) ; adaptateurs Google sur réponses reconstruites (`tests/messages/data/`) rejouées par `httpx2.MockTransport` | Le critère porte sur ce qui est écrit en base : il se vérifie sur la vraie base |

## Mesures et essai (04/10)

| Contrôle | Résultat |
|---|---|
| Critère, par les tests (`tests/messages/test_usecases.py`, `test_service.py`) | Une collecte relancée ne télécharge aucun message (`get` jamais appelé), n'écrit rien et passe une liste vide au crochet ; le crochet ne reçoit que des messages déjà validés en base ; un message en échec n'est pas écrit, la collecte est partielle et il est repris à la suivante ; deux collectes simultanées n'écrivent jamais un message deux fois ; un arrêt pendant la collecte la close « interrompue », une collecte restée ouverte est close au démarrage |
| Vérification globale | `docker compose run --rm --build check` : 1 244 tests (75 de plus pour E1), **1 min 09 à 1 min 27** avec `pytest -n auto` (1 min 47 avant xdist, sans E1) |
| Migration `0013` sur la base de développement | `upgrade` → `downgrade -1` → `upgrade head` |
| Essai dans Chromium (instance à part : schéma jetable de `test-db`, compte fictif, Google simulé par une page de consentement locale, faux Gmail sur les messages reconstruits) | « Connecter une boîte Gmail » → consentement → « Boîte connectée », collecte suivie à l'écran, 3 messages (retour, alerte, pièce jointe) avec « Retours » / « Alertes » ; « Relever maintenant » → « 0 nouveau message (3 déjà relevés) » ; « Déconnecter » → « Déconnectée », messages gardés, « Reconnecter » ; refus chez Google → « Tu as refusé l'accès… », aucune boîte ajoutée. Console : seul le 400 voulu de la page de refus |

Corrigé pendant l'essai : la liste des messages ne suivait pas la collecte (seules les boîtes étaient interrogées : les deux
le sont ensemble, `messages/content.html`) ; course entre la réponse à « Relever maintenant » et le planificateur qui a
déjà sorti la tâche de sa file sans avoir écrit sa ligne : l'écran interrogeait trop tôt l'ancienne collecte
(`launched`, comme la bannière de la veille ; test `test_the_screen_follows_a_collection_the_planner_already_took`).

Recette avec Nicolas (réseau réel, à faire) : créer le client Google (`docs/procedures/e1-gmail/`), connecter ses boîtes,
deux « Relever maintenant » de suite (la seconde : 0 nouveau), vérifier que les promotions n'arrivent que par la requête
*alertes* et que Google accepte `http://127.0.0.1:8000` comme adresse de retour.

## Hors E1

Classification et preuves (E2) ; offres tirées des alertes (E3) ; transition de candidature et écran des décisions (E4) ;
⚙️ Système complet (F1) ; suppression d'une boîte et de ses messages ; rotation de `ROCKY_SECRET_KEY`.
