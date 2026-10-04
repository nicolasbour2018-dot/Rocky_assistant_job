# E1 — Brancher Gmail sur le nouveau Rocky

Étapes faites **par Nicolas** : l'agent ne lit ni n'écrit aucun secret (`AGENTS.md`, §3). Décision :
`docs/decisions/E1-collecte.md`.

## 1. Le client Google (une fois)

Dans <https://console.cloud.google.com/> (le projet de l'ancien Rocky peut servir) :

1. **API et services → Bibliothèque** : activer l'**API Gmail**.
2. **Google Auth Platform → Accès aux données** : ajouter le seul scope
   `https://www.googleapis.com/auth/gmail.readonly`.
3. **Audience** : type « Externe » ; **état de publication « En production »**. En mode « Test », Google retire l'accès
   au bout de **7 jours** et la boîte passe « À reconnecter ». En production sans validation, Google affiche un
   avertissement « application non validée » (Continuer → autoriser) ; c'est suffisant pour moins de 100 personnes
   (plan §5 : la validation viendra avec les alpha-testeurs).
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
`ROCKY_SECRET_KEY` (la clé ci-dessus). Une clé qui n'est pas une clé Fernet empêche Rocky de démarrer, avec le nom de
la variable.

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
