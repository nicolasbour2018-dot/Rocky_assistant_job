# E1 — Brancher Gmail sur le nouveau Rocky

Étapes faites **par Nicolas** : l'agent ne lit ni n'écrit aucun secret (`AGENTS.md`, §3). Décision :
`docs/decisions/E1-collecte.md`.

## 1. Le client Google (une fois)

Dans <https://console.cloud.google.com/> (le projet de l'ancien Rocky peut servir) :

1. **API et services → Bibliothèque** : activer l'**API Gmail**.
2. **Google Auth Platform → Accès aux données** : ajouter le seul scope
   `https://www.googleapis.com/auth/gmail.readonly`.
3. **Audience** : type « Externe », état de publication **« Test »**, et dans **Utilisateurs tests** chaque adresse
   Gmail à connecter (une boîte absente de la liste est refusée par Google). En mode « Test », Google retire l'accès
   au bout de **7 jours** : la boîte passe « À reconnecter » dans 📬 Messages, un clic sur « Reconnecter » suffit.
   Le passage « En production » demande une page d'accueil et une page de confidentialité (page « Branding ») : il se
   fera avec le VPS et la validation de l'application (plan §5 ; recette d'E1).
4. **Clients → Créer un client** : type **« Application Web »** (pas « Application de bureau », celui de l'ancien
   Rocky). URI de redirection autorisée : `http://127.0.0.1:8000/messages/gmail/retour`, c'est-à-dire
   `ROCKY_PUBLIC_URL` suivi de `/messages/gmail/retour`, au caractère près. Google accepte `http` pour une adresse
   locale (`127.0.0.1`, `localhost`). S'il refusait `127.0.0.1`, utiliser `http://localhost:8000/…`, mettre
   `ROCKY_PUBLIC_URL=http://localhost:8000` et ouvrir Rocky à cette adresse : le cookie de session est lié à l'hôte.

## 2. Le `.env`

```sh
# La clé qui chiffre les jetons en base (à garder : la changer oblige à reconnecter les boîtes)
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Remplir dans `.env` : `ROCKY_GOOGLE_CLIENT_ID`, `ROCKY_GOOGLE_CLIENT_SECRET` (du client de l'étape 1.4) et
`ROCKY_SECRET_KEY` (la clé ci-dessus). **`ROCKY_SECRET_KEY` ne vient pas de Google** : c'est la clé de Rocky, générée
sur l'ordinateur par la commande ci-dessus (44 caractères finissant par `=`), dans son propre terminal pour qu'elle ne
s'affiche nulle part ailleurs. Le secret donné par Google va dans `ROCKY_GOOGLE_CLIENT_SECRET`. Une clé qui n'est pas
une clé Fernet empêche Rocky de démarrer, migrations comprises, avec le nom de la variable (piège de la recette).

L'URI de redirection est une sécurité : Google n'envoie le code d'autorisation qu'aux adresses déclarées, et un écart
s'affiche chez Google (« Erreur 400 : redirect_uri_mismatch »). Une boîte qui arrive « Connectée » prouve qu'elle est
juste.

## 3. Connecter et relever

```sh
docker compose up -d --build --wait app   # le service migrate applique la migration 0013
```

1. <http://127.0.0.1:8000/messages> → **Connecter une boîte Gmail** → choisir le compte, accepter la lecture.
2. Retour sur 📬 Messages : « Boîte connectée », la première collecte (30 jours) part aussitôt.
3. Autre boîte : refaire 1 (Google propose de choisir le compte).
4. **Relever maintenant** deux fois de suite : la seconde dit « 0 nouveau message (N déjà relevés) ».

Sans navigateur : `docker compose run --rm app rocky-admin messages <email>` (réseau réel).

## Retirer l'accès

**Déconnecter** dans 📬 Messages révoque le jeton chez Google et l'efface ; les messages relevés restent. On peut
aussi retirer Rocky dans le compte Google (Sécurité → Applications tierces) : la boîte passe « À reconnecter » à la
collecte suivante.
