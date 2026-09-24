# B3 — Comptes et sessions

Date : 24/09/2026 · Étape : B3 (plan v2)

Critère de sortie : « Rechargement, URL directe et redémarrage du navigateur gardent la session ; la déconnexion
l'invalide. »

## Décisions métier (validées avec Nicolas)

| Sujet | Décision | Raison |
|---|---|---|
| Création des comptes | **Sur invitation** : pas d'inscription publique. `rocky-admin invite <email>` crée un compte en attente et envoie un lien d'activation ; la personne choisit son mot de passe. Réinviter un compte en attente émet un nouveau lien et annule les anciens ; inviter un compte actif est refusé | Le VPS sera exposé sur Internet ; les alpha-testeurs (§5) sont choisis par Nicolas. |
| Durée de session | **7 jours d'inactivité**, renouvellement glissant (D11), sans plafond absolu | Choix de Nicolas : une semaine sans visite impose de se reconnecter. |
| E-mails | **Vrai SMTP dès maintenant** (`ROCKY_SMTP_*`) ; les tests n'envoient jamais d'e-mail (faux adaptateur) | Choix de Nicolas. |
| Mot de passe oublié | Lien valable 1 h, envoyé seulement à un compte actif ; réponse identique dans tous les cas ; la réinitialisation ferme toutes les sessions du compte | Repris de l'ancien Rocky. |
| Lien d'activation | Valable 7 jours, à usage unique | Laisser à l'invité le temps de répondre. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Emplacement | `rocky/system/auth/` : `rules.py` (pur) → `usecases.py` → `sql.py` → `web.py`, plus `mail.py` et `admin.py` | Forme interne d'un module (`AGENTS.md` §4) ; tout le SQL d'authentification dans l'accès SQL de `system` (constat Codex). |
| Port de stockage | Un seul `Protocol` `AuthStore` pour l'agrégat (comptes, jetons, sessions, événements), implémenté par `SqlAuthStore(conn)` et par un faux en mémoire | Cas d'usage testables sans SQL, sans créer une interface par table. |
| Transactions | L'appelant (route, CLI) ouvre **une** transaction par cas d'usage ; le magasin travaille sur cette connexion | Une activation (jeton consommé, compte activé, session ouverte, événement) réussit ou échoue d'un bloc ; l'ancien Rocky le faisait en deux transactions. |
| Échecs attendus | Résultats typés (identifiants faux, lien invalide), pas d'exception | Le compteur d'échecs d'une connexion ratée est validé avec le reste. |
| E-mails | Les cas d'usage renvoient les e-mails à envoyer ; l'appelant les envoie **après** la validation ; un échec d'envoi est affiché | Jamais de lien envoyé pour un jeton non enregistré ; le cas inverse se rattrape en réinvitant. |
| Jetons | 32 octets aléatoires ; seule l'empreinte SHA-256 est stockée ; consommation atomique (`UPDATE … WHERE used_at IS NULL AND expires_at > now RETURNING`) | Un lien ne sert qu'une fois, même en double clic. |
| Mots de passe | argon2 ; au moins 12 caractères, sans règle de composition ; hachage factice quand le compte n'existe pas | Temps de réponse identique : le formulaire ne révèle pas quelles adresses ont un compte. |
| Verrou | 5 échecs consécutifs → verrou de 15 min ; message identique à un mot de passe faux | Repris de l'ancien Rocky. |
| Cookie | `rocky_session` : `HttpOnly`, `SameSite=Lax`, `Secure` si `ROCKY_PUBLIC_URL` est en `https`, `Max-Age` de 7 jours reposé à chaque prolongation | Un cookie sans `Max-Age` disparaît à la fermeture du navigateur : c'est le `Max-Age` qui fait tenir la session au redémarrage. |
| Prolongation | Au plus une écriture par heure et par session | Pas d'écriture en base à chaque requête. |
| Redirection | Page protégée sans session → `303` vers `/connexion?suite=<chemin>` ; retour au chemin après connexion ; seuls les chemins locaux sont acceptés | Critère « URL directe » ; pas de redirection vers un autre site. |
| Formulaires | Toute écriture en `POST` ; pas de jeton CSRF | `SameSite=Lax` n'envoie pas le cookie sur un `POST` venu d'un autre site. |
| Journal | `system.account_invited`, `system.account_activated`, `system.password_reset`, `system.account_locked` ; `events.account_id` → `accounts` (nullable, sans cascade) | Transitions du compte ; connexions et déconnexions restent dans `sessions`. Constat B2 → B3. |
| Pages | Gabarits Jinja minimaux, sans style ; accueil provisoire protégé (« Connecté en tant que … ») ; adresses en français (`/connexion`, `/deconnexion`, `/activation`, `/mot-de-passe-oublie`, `/reinitialisation`) | La coque et le style arrivent en B4. |
| SMTP absent | L'application démarre ; invitation et mot de passe oublié échouent avec un message explicite | Pas d'erreur silencieuse ; la connexion reste possible. |
| `--print-link` | `rocky-admin invite --print-link` affiche le lien au lieu de l'envoyer | Secours si le SMTP est en panne ; vérifications sans écrire à personne. |

## Dépendances ajoutées

| Dépendance | Groupe | Justification |
|---|---|---|
| `argon2-cffi` | exécution | hachage des mots de passe (déjà utilisé par l'ancien Rocky) |
| `jinja2` | exécution | gabarits HTML (D6) |
| `python-multipart` | exécution | lecture des formulaires par FastAPI |

## Mesures

Mesuré le 24/09/2026.

**Critère de sortie, automatisé** (`tests/system/auth/test_web.py`, `TestClient`, faux e-mail) :
activation → page protégée ; rechargement ; URL directe sans session → `/connexion?suite=%2F%3Fvue%3Dliste` →
retour à `/?vue=liste` après connexion ; nouveau client ne gardant que le cookie → toujours connecté ;
déconnexion → le même cookie rejoué est refusé, l'autre session reste ouverte. Vert.

**Critère de sortie, serveur réel** (`docker compose up app`, compte d'essai créé avec `--print-link`) :

| Contrôle | Résultat |
|---|---|
| Activation dans Chromium (Playwright) | page d'accueil « Connecté en tant que … » ; `document.cookie` vide (`HttpOnly`) |
| Rechargement, puis URL directe `/?vue=liste` | toujours connecté |
| Cookie posé par le serveur (`curl`) | `HttpOnly; Max-Age=604800; Path=/; SameSite=lax` : cookie persistant, écrit sur disque par le navigateur |
| Réouverture d'un onglet après fermeture | toujours connecté (Playwright ne ferme que l'onglet : la preuve du redémarrage est le `Max-Age`) |
| Déconnexion dans le navigateur, puis `/` | redirigé vers `/connexion?suite=%2F` |
| Ancien cookie rejoué avec `curl` après `POST /deconnexion` | `200` avant, `303` vers la connexion après |

Autres contrôles :
- 104 tests verts ; vérification globale en 25 s avec reconstruction de l'image.
- `migrate` applique `0002` sur la base de développement ; `downgrade base` puis `upgrade head` fonctionnent.
- Le compte d'essai a été effacé par cette remise à zéro de la base de développement (le journal refuse toute
  suppression) : la base était vide avant l'essai et l'est après.
- SMTP réel, vérifié par Nicolas le 24/09/2026 : `rocky-admin invite <son adresse>` → e-mail reçu → mot de passe
  choisi par le lien d'activation, compte actif. C'est le premier compte réel de la base de développement.
