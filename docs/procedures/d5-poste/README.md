# D5 — Le poste Rocky (préremplissage dans un navigateur visible)

> **En sommeil depuis la recette du 04/10/2026** (décision D5, « Recette de Nicolas ») : échec sur 2 annonces réelles
> sur 2, les sites des recruteurs passant par leurs propres connexions avant tout formulaire. Rocky ne propose plus
> le préremplissage (`candidatures.web.PREFILL_ENABLED = False`) ; inutile de lancer le poste. Cette procédure est
> gardée pour le jour où la fonction sera réactivée.

Décision : `docs/decisions/D5-revisions-envoi.md` (Q1, Q4, Q6). Rocky tourne dans Docker et ne peut pas ouvrir de
fenêtre sur l'ordinateur : le **poste Rocky** est un petit programme lancé sur l'ordinateur lui-même. Quand tu
confirmes « Préremplir » dans l'étape Envoi d'un dossier, Rocky lui transmet l'adresse du formulaire, tes coordonnées,
le message d'accompagnement validé et les PDF de la révision exacte (relus et vérifiés par leur hash). Le poste ouvre
un onglet de Chromium, remplit ce qu'il reconnaît et **ne clique sur rien** : tu relis, tu complètes, tu envoies
toi-même, puis tu reviens dans Rocky dire « J'ai envoyé ma candidature ».

## 1. Installer (une fois)

Depuis le dépôt, sur l'ordinateur (pas dans Docker) :

```sh
uv sync
uv run playwright install chromium   # le navigateur complet, avec fenêtre
```

## 2. Lancer

```sh
uv run rocky-poste
```

Le terminal affiche « Poste Rocky prêt sur http://127.0.0.1:8765 ». Laisse-le ouvert pendant tes candidatures ;
`Ctrl+C` l'arrête. Options : `--port` (8765 par défaut ; changer aussi `ROCKY_WORKSTATION_URL` dans le `.env`) et
`--profil` (dossier du profil du navigateur, `~/.rocky/navigateur` par défaut).

Le profil du navigateur est **persistant** : connecte-toi une fois à LinkedIn, Welcome to the Jungle ou à l'espace
candidat d'un employeur dans la fenêtre du poste, la connexion reste pour les fois suivantes. Ce dossier est hors du
dépôt et n'est jamais versionné.

## 3. Ce que fait le poste

- Il n'écoute que sur `127.0.0.1` et ne répond qu'à Rocky : une page web ouverte dans ton navigateur ne peut pas le
  déclencher (JSON exigé, en-tête `Origin` refusé, en-tête `Host` vérifié).
- Il remplit un champ **vide** reconnu par ses attributs (`autocomplete`, `name`, `id`) ou par son libellé (FR, EN) :
  nom complet, e-mail, téléphone, ville, code postal, LinkedIn, GitHub, portfolio, message. Un champ déjà rempli par le
  site est laissé tel quel.
- Il dépose le CV et la lettre dans les champs fichier qui les nomment (« cv », « resume », « lettre », « cover »…),
  sinon dans le premier champ libre, sous les noms `CV_<Nom>_<FR|EN>.pdf` et `Lettre_<Nom>_<FR|EN>.pdf`.
- Il rend à Rocky un rapport : ce qui est rempli, ce qui reste à faire avec sa raison (« champ introuvable »,
  « déjà rempli », « aucun champ de fichier pour lui »). Rocky l'affiche dans l'étape Envoi et passe le dossier à
  « Préremplie ».

## 4. Si Rocky dit « Le poste Rocky ne répond pas »

- Le poste n'est pas lancé : `uv run rocky-poste`.
- Rocky tourne dans Docker et joint le poste par `host.docker.internal` (Docker Desktop ; déclaré aussi dans
  `docker-compose.yml` pour Linux). Vérifié le 04/10/2026 : un service lié à `127.0.0.1` sur le Mac répond depuis un
  conteneur.
- Sur un serveur sans écran (VPS), il n'y a pas de poste : ouvre le site de candidature toi-même (« Ouvrir le site de
  candidature ↗ ») et télécharge les PDF générés.
