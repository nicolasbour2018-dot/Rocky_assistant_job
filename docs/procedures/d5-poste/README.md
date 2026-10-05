# Le poste Rocky (navigateur visible sur l'ordinateur)

Décisions : `docs/decisions/E5-lecture-assistee.md` (lecture assistée) et `docs/decisions/D5-revisions-envoi.md` (Q1,
Q4, Q6 : préremplissage). Rocky tourne dans Docker et ne peut pas ouvrir de fenêtre sur l'ordinateur : le **poste
Rocky** est un petit programme lancé sur l'ordinateur lui-même, qui pilote un Chromium **visible**. Il ne clique sur
rien et ne passe aucun défi à ta place. Il n'écoute que sur `127.0.0.1` et ne répond qu'à Rocky : une page web ouverte
dans ton navigateur ne peut pas le déclencher (JSON exigé, en-tête `Origin` refusé, en-tête `Host` vérifié).

- **Lecture assistée** (E5) : dans la fiche d'une offre incomplète, « Ouvrir dans le navigateur » ouvre l'annonce dans
  un onglet du poste ; tu passes toi-même l'éventuel défi, puis « Lire la page affichée » : Rocky lit la page telle
  qu'elle est affichée et complète l'offre (section 3).
- **Préremplissage** (D5) : **en sommeil depuis la recette du 04/10/2026** (échec sur 2 annonces réelles sur 2, les
  sites des recruteurs passant par leurs propres connexions avant tout formulaire). Rocky ne le propose plus
  (`candidatures.web.PREFILL_ENABLED = False`) ; la section 4 est gardée pour le jour où il sera réactivé.

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

Le terminal affiche « Poste Rocky prêt sur http://127.0.0.1:8765 ». Laisse-le ouvert pendant que tu tries tes offres ;
`Ctrl+C` l'arrête. Options : `--port` (8765 par défaut ; changer aussi `ROCKY_WORKSTATION_URL` dans le `.env`) et
`--profil` (dossier du profil du navigateur, `~/.rocky/navigateur` par défaut).

Le profil du navigateur est **persistant** : connecte-toi une fois à LinkedIn, Welcome to the Jungle ou à l'espace
candidat d'un employeur dans la fenêtre du poste, la connexion reste pour les fois suivantes. Ce dossier est hors du
dépôt et n'est jamais versionné.

## 3. Lecture assistée

- « Ouvrir dans le navigateur » (touche `e`) : le poste ouvre l'adresse de l'offre dans un nouvel onglet et le met au
  premier plan. Passe l'éventuel défi, attends que l'annonce soit affichée en entier.
- **Pas pour Apec** : Apec refuse le navigateur du poste (« Access is temporarily restricted », recette du 05/10) ; une
  offre Apec se complète à la main, par « Coller la description » (décision E5, Q8).
- « Lire la page affichée » (touche `e`) : le poste rend à Rocky l'adresse affichée et la page telle qu'elle est
  dessinée. Rocky en tire la description (annonce structurée, bloc de description connu, sections Apec) et les faits
  qui manquaient ; le score est recalculé aussitôt. L'onglet reste ouvert.
- Rocky refuse une page d'un autre site que celui de l'offre (« la page affichée n'est plus l'annonce ») ; une page
  sans annonce lisible ne remplace pas la description (« colle la description »). Un onglet fermé, ou un poste relancé
  entre les deux gestes : rouvre l'annonce.

## 4. Préremplissage (en sommeil)

- Il remplit un champ **vide** reconnu par ses attributs (`autocomplete`, `name`, `id`) ou par son libellé (FR, EN) :
  nom complet, e-mail, téléphone, ville, code postal, LinkedIn, GitHub, portfolio, message. Un champ déjà rempli par le
  site est laissé tel quel.
- Il dépose le CV et la lettre dans les champs fichier qui les nomment (« cv », « resume », « lettre », « cover »…),
  sinon dans le premier champ libre, sous les noms `CV_<Nom>_<FR|EN>.pdf` et `Lettre_<Nom>_<FR|EN>.pdf`.
- Il rend à Rocky un rapport : ce qui est rempli, ce qui reste à faire avec sa raison (« champ introuvable »,
  « déjà rempli », « aucun champ de fichier pour lui »). Rocky l'affiche dans l'étape Envoi et passe le dossier à
  « Préremplie ».

## 5. Si Rocky dit « Le poste Rocky ne répond pas »

- Le poste n'est pas lancé : `uv run rocky-poste`.
- Rocky tourne dans Docker et joint le poste par `host.docker.internal` (Docker Desktop ; déclaré aussi dans
  `docker-compose.yml` pour Linux). Vérifié le 04/10/2026 : un service lié à `127.0.0.1` sur le Mac répond depuis un
  conteneur.
- Sur un serveur sans écran (VPS), il n'y a pas de poste : colle la description d'une offre incomplète
  (« Coller la description »), ouvre le site de candidature toi-même et télécharge les PDF générés.
