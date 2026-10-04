# D5 — Révisions et envoi

Date : 04/10/2026 · Étape : D5 (plan v2) · Préparation : mode plan, questions à Nicolas (Q1–Q7)

Critère de sortie (plan) : « Deux générations → deux PDF distincts récupérables ; l'envoi est lié à la révision
exacte ».

## Constats de départ

| Constat | Source |
|---|---|
| Les PDF du dossier (CV ciblé, lettre) sont recalculés à chaque téléchargement ; rien n'est stocké ; la lettre porte la date du jour | `rocky/candidatures/web.py` (`cv_pdf`, `letter_pdf`) ; constat D4 → D5 |
| « J'ai envoyé » ne fait que passer à l'étape `sent` : ni date choisie, ni canal, ni document | `send_step.html`, route `move` ; décision D3, Q25 |
| La lettre « envoyée » se déduit des dates (version en vigueur au dernier passage à « Envoyée ») | `letter_view.py` (`version_at`) ; décision D4, Q20 |
| Stockage par hash, idempotent, relu avec vérification, chemins relatifs à la racine | `rocky/system/files.py` (`FileStore`) ; décision D2 |
| Les octets d'un PDF de Chromium changent à chaque rendu (date de création) ; le HTML rendu, lui, est déterministe (`CvPdf.html_sha256`) | `rocky/system/render.py`, `rocky/profil/cv/rendering.py` |
| L'ancien préremplissage lançait Chromium **visible** dans le processus de l'application, avec des `except Exception: continue` par champ | `dashboard/rocky/browser_apply.py`, `scripts/prefill_application.py` (historiques) |
| Le nouveau Rocky tourne dans Docker : un conteneur ne peut pas ouvrir de fenêtre sur le Mac | `docker-compose.yml` |

## Décisions métier (Nicolas, 04/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Préremplissage | Par un **poste Rocky** lancé sur le Mac (`uv run rocky-poste`). Rocky lui transmet la révision exacte ; le poste ouvre un Chromium **visible** (profil persistant), remplit le formulaire et ne clique **jamais** sur un bouton. Il resservira à la lecture assistée (E5). |
| Q2 | Naissance d'une révision | Geste **« Générer les PDF à envoyer »** (langue FR ou EN) dans l'étape Envoi : le CV ciblé, plus la lettre en vigueur de cette langue s'il y en a une. Les téléchargements servent ces octets, hash vérifié. « Régénérer » ajoute des révisions ; les anciennes restent récupérables (« Versions précédentes »). L'écran signale un CV ou une lettre changé depuis. Les aperçus des étapes CV et Lettre restent éphémères. |
| Q3 | Canal | Site de l'entreprise, LinkedIn, Indeed, Welcome to the Jungle, Apec, Hellowork, France Travail, E-mail, Autre (à préciser). Proposé d'après le domaine du lien de candidature, modifiable. Date d'envoi : celle du jour par défaut, modifiable, jamais dans le futur. |
| Q4 | Ce que le poste remplit | L'**identité** (nom, e-mail, téléphone, ville, code postal, LinkedIn, GitHub, portfolio), le **CV et la lettre** de la révision dans les champs fichier, le **message d'accompagnement** validé dans un champ libre reconnu. |
| Q5 | Confirmation d'envoi | Les dernières révisions sont cochées d'office, une révision périmée est signalée. Sans révision : générer, ou choisir explicitement « Envoyée sans document de Rocky ». Rien n'est lié en silence. |
| Q6 | Étape « Préremplie » | Le poste a pris le formulaire : le dossier passe à « Préremplie » (auteur `user`, « Confirmer l'envoi » à J+1), annulable. Le rapport du poste (champs remplis, à faire toi-même) s'affiche dans l'étape Envoi. |
| Q7 | Recette | Sur 2 offres réelles, dont une en anglais ; elle reprend les restes de D4 (lettre anglaise d'un dossier, message d'accompagnement). |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Révisions | Table `document_revisions` en ajout seul (le préfixe `application_` ferait dépasser aux clés étrangères les 63 caractères de PostgreSQL) : type (`cv`, `letter`), langue, chemin relatif, hash, empreinte des entrées, version de lettre ; fichier dans `FileStore` (`comptes/<id>/candidatures/<sha>.pdf`) | Constat A1 → D5 : chemins relatifs, vérifiés par hash ; un PDF n'est jamais réécrit. |
| Empreinte | CV : `sha256` du HTML rendu, du gabarit actif et de la photo, calculée sans Chromium ; lettre : la version en vigueur (la date est figée dans la révision et ne compte pas) | Les octets du PDF changent à chaque rendu : seule l'entrée dit si le document a changé. |
| Fichier sans ligne | Le PDF est écrit avant la transaction ; si celle-ci échoue, il reste un fichier adressé par son hash, sans ligne, sans effet | Rendu lent hors transaction ; un fichier en trop ne fausse rien. |
| Envoi | Table `application_sendings` : le changement « Envoyée » documenté (`change_id`, unique), date, canal, précision, révisions et message liés (facultatifs) ; écrit avec le changement et son événement dans **une** transaction | Annuler le changement retire l'envoi sans autre écriture ; critère de D1 tenu. |
| Envoi depuis la liste | Choisir « Envoyée » dans la liste brute mène au formulaire de confirmation | Aucun envoi non documenté. |
| Relance | « Relancer » à la date d'envoi + 7 jours | Un envoi saisi le lendemain garde sa relance. |
| Envois d'avant D5 | Gardés tels quels, affichés « documents non liés (avant D5) » ; la lettre envoyée s'y déduit encore des dates | Décision D3, constat D3 → D5. |
| Poste | `rocky/system/workstation.py` (protocole, client de l'application) et `workstation_host.py` (serveur du Mac, Playwright) ; commande `rocky-poste` | Adaptateur « navigateur » du plan (§3), réutilisable par E5. |
| Pas de ticket | Rocky appelle le poste (`ROCKY_WORKSTATION_URL`, `http://host.docker.internal:8765` par défaut) avec les champs et les PDF relus et vérifiés ; le poste répond après le remplissage avec son rapport | Aucune route de Rocky ouverte au poste ; Rocky sait si le poste a pris le formulaire avant d'écrire « Préremplie ». |
| Garde du poste | Écoute sur `127.0.0.1` seulement ; exige `Content-Type: application/json` ; refuse un en-tête `Origin` ; `Host` dans une liste fermée | Une page web ne peut ni l'appeler (pré-vol CORS) ni passer par un rebinding DNS. |
| Fichiers déposés | Donnés à Playwright par leur contenu, nommés `CV_<Nom>_<FR/EN>.pdf` et `Lettre_<Nom>_<FR/EN>.pdf` | Le recruteur voit ce nom ; aucun fichier temporaire à gérer. |
| Rapport | Chaque champ ou fichier qui échoue va dans le rapport avec sa raison | Plus d'exception avalée (AGENTS §4). |
| Dépendances | Aucune ajoutée : `playwright` et `httpx2` déjà présents, `http.server` de la bibliothèque standard | — |

## Essai dans un navigateur (Claude, 04/10)

Instance à part : Rocky lancé sur le Mac (schéma jetable de `test-db`, compte fictif « Camille Martin »), offre dont le
lien de candidature est un formulaire de démonstration local (`127.0.0.1:8899`), **vrai poste Rocky**
(`uv run rocky-poste`, profil de navigateur jetable) ; interface pilotée par Playwright.

| Parcours | Résultat |
|---|---|
| Lettre validée, « Lettre prête », « Générer les PDF à envoyer » | CV et lettre figés, date et empreinte affichées |
| Lettre modifiée | Seule la lettre est « a changé depuis » ; le CV, inchangé, ne l'est pas |
| « Régénérer les PDF » | 4 révisions, « Versions précédentes (2) » ; chacune téléchargée : 4 PDF distincts, hash identique à l'empreinte affichée, `CV_Camille_Martin_FR.pdf` / `Lettre_Camille_Martin_FR.pdf` |
| « Préremplir avec le poste Rocky » | Confirmation : valeurs, fichiers et empreintes ; case cochée → Chromium visible sur le formulaire ; rempli : nom, e-mail, téléphone, ville, LinkedIn, CV, lettre ; à faire : code postal et GitHub (absents du formulaire). Dossier « Préremplie » |
| Poste appelé depuis une page web (`Origin`) | Refusé (403) |
| « J'ai envoyé ma candidature » : LinkedIn, **ancienne** lettre cochée | « Envoyée le 04/10/2026 via LinkedIn », liens vers les révisions exactes (CV 3, lettre 2) ; étape Lettre : « Envoyée avec la version du 04/10 à 15:26 ; la lettre a été modifiée depuis » ; « Relancer » le 11/10 |
| Console | Aucune erreur |

Corrigé après l'essai : accord « générée » / « envoyée » pour la lettre.

Vérification globale : verte, 1 114 tests, 1 min 50 (proche de la limite de 2 min, section 8).
