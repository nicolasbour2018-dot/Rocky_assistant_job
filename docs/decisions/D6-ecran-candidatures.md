# D6 — Écran Candidatures

Date : 04/10/2026 · Étape : D6 (plan v2) · Préparation : mode plan, questions à Nicolas (Q1–Q8)

Critère de sortie (plan) : « Une relance due est retrouvée en moins de 3 clics. »

## Constats de départ

| Constat | Source |
|---|---|
| L'écran 📝 Candidatures est la liste brute de D1 (étape par menu et bouton, prochaine action, différer, annuler), plus « À préparer » (D3, Q26) | `rocky/candidatures/templates/candidatures/list.html` |
| La page du dossier empile CV, lettre et envoi ; chaque paragraphe de la lettre est montré deux ou trois fois ; la langue se choisit par des liens en haut de l'étape Lettre, séparément pour le CV | `dossier.html`, `cv_step.html`, `letter_step.html` ; constat D4 → D6 (« le parcours est juste horrible ») |
| L'étape Envoi s'allonge : PDF, site, message, confirmation | `send_step.html` ; constat D5 → D6 |
| « Le suivi viendra ici » : ni notes, ni chronologie, ni action faite | `send_step.html` (`sent_block`) |
| Aucune lecture du journal d'événements ; tous les événements `candidatures.*` ont pour sujet `application` et son identifiant | `rocky/system/events.py`, `usecases._event` ; constat B2 → D6 |
| « Préparer » renvoie déjà vers le dossier (`HX-Redirect`) | `web.prepare` ; décision D3, Q25 ; constat D1 → D6 |
| La date limite d'une annonce est lue par l'analyse, jamais utilisée par les candidatures | `offres/analysis/rules.py` (`_deadline`) ; constat D1 → D6 |
| `p` est déjà « Plus tard » dans le mode tri | `offres/decisions.py` (`DECISION_KEYS`) |
| Aucune clé étrangère ne vise `cv_templates` ; 19 gabarits sur le compte de Nicolas, dont 13 essais | migrations `0007`–`0009` ; constat D3 → D6 |
| `rocky/candidatures/web.py` fait 1 864 lignes | — |

## Décisions métier (Nicolas, 04/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Écran liste | **Liste dense à onglets** avec compteurs : À faire (prochaine action due ou en retard, ouvert par défaut), À préparer (offres « Intéressé » sans dossier), En préparation, Prêtes, Suivi, Closes. Une ligne : offre, étape, prochaine action datée, date limite, gestes en un clic. |
| Q2 | Dossier | **Une étape à la fois** : fil 1. CV · 2. Lettre · 3. Envoi · 4. Suivi, toujours cliquable ; une action principale par étape ; chaque étape a son adresse ; le dossier s'ouvre sur l'étape en cours (Suivi une fois envoyée ou close). |
| Q3 | Lettre | **Un seul texte modifiable par paragraphe**, prérempli avec la version retenue. Après « Adapter à l'annonce », un sélecteur « Ta lettre · Gemini » remplace le texte ; écrire dedans en fait « ta version ». Origines et version proposée gardées (D14). Aperçu de la page à côté. |
| Q4 | Langue | **Une langue par dossier**, choisie dans l'en-tête (français par défaut), enregistrée et journalisée ; elle vaut pour le CV, la lettre, le message et les PDF. Le travail fait dans l'autre langue est gardé. |
| Q5 | « Fait » | Note l'action faite (datée, dans la chronologie) et **propose aussitôt la suivante** d'après l'étape (après « Relancer » : « Relancer » à J+7), modifiable ; annulable comme tout changement. |
| Q6 | Notes | **Ajout seul, datées**, dans la chronologie ; une note se retire (retrait tracé, rien n'est effacé), elle ne se réécrit pas. |
| Q7 | Chronologie | Les **faits marquants** : création, changements d'étape, envoi, actions faites, notes, annulations, lettre validée ou écartée, PDF générés. Les réglages fins (sélection du CV, report ou modification d'une action, langue, message) sous « Tout afficher ». Lue dans le journal, en français. |
| Q8 | Périmètre | Inclus : raccourci « Intéressé et préparer » depuis le mode tri (D3 → D6) ; date limite affichée et bornant l'échéance proposée (D1 → D6) ; fiche d'offre à jour après « Préparer » (D1 → D6) ; suppression d'un gabarit de CV inactif dans Profil & kit (D3 → D6). |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| « Fait » | `ChangeKind.ACTION_DONE` dans `application_changes` : il fixe la prochaine action suivante (proposition de l'étape, ou aucune pour l'Entretien, dont la date se saisit). L'action faite se **déduit** de l'action en vigueur avant lui. Événement `candidatures.action_done` (`done`, `next_action`). Proposé aux étapes après l'envoi seulement | État calculé (D1) : aucune colonne en plus ; « Annuler » le défait sans code de plus. Avant l'envoi, l'action (« Finir le dossier », « Envoyer ») se fait par le geste de l'étape. |
| Date limite | `rules.proposal` borne à la date limite, si elle n'est pas passée, l'échéance proposée en préparation et pour « Prête à envoyer ». Lue par `offres.web.offer_deadlines` (date de la source, sinon celle lue dans l'annonce) | Constat D1 → D6 ; `candidatures` ne lit pas le SQL d'`offres`. |
| Notes | Table `application_notes` en ajout seul : un texte, ou le retrait d'une note (`removes_id` unique). Événements `candidatures.note_added`, `candidatures.note_removed`. Hors de « Annuler » | Une note n'est pas un changement du dossier : « Annuler » défait toujours une étape ou une action (D1, Q6). |
| Langue | Table `application_languages` en ajout seul, la dernière en vigueur, français sans ligne. Événement `candidatures.language_chosen`. Hors de « Annuler » | Même raison ; les routes lisent la langue du dossier au lieu d'un paramètre. |
| Chronologie | `system.events.events_about` lit le journal d'un sujet (index `ix_events_subject`) ; `candidatures/timeline.py` (règles pures) donne libellé et rang de chaque type connu ; un test exige un libellé pour chaque type écrit par les cas d'usage | Fin du constat B2 → D6 ; aucun événement ignoré en silence. |
| Onglets et étapes | `rules.tab_of` (pur) ; `/candidatures?vue=…` ; `Step.FOLLOW` ; `/candidatures/{id}?etape=cv|lettre|envoi|suivi` | Pas de conflit avec les routes `POST /{id}/cv` et `/{id}/envoi`. |
| Origine d'un paragraphe | Calculée du texte envoyé : l'original → générique, la version de Gemini → adaptée, autre → modifiée | Un seul texte à l'écran sans perdre l'étiquette D14. |
| Raccourci du tri | Bouton « Valider et préparer » (touche `d`) dans le panneau « Pourquoi intéressé ? » du tri : mêmes champs postés vers `/candidatures/offre/{id}/preparer` | `offres` ne connaît de `candidatures` que des URL ; la décision et le dossier restent écrits ensemble (D1, Q8, Q9). |
| Gabarit de CV | Suppression d'un gabarit **inactif** après confirmation : la ligne `cv_templates` disparaît, son dossier immuable reste dans le stockage ; événement `profil.cv_template_deleted` ; refus pour le gabarit actif | Configuration, pas une décision (précédent : `profil.track_deleted`) ; aucun fichier réécrit ni purgé. |
| `web.py` | Découpé : liste et gestes (`web.py`), pages du dossier (`dossier_web.py`) ; déplacement sans changement de comportement d'abord | Lisibilité d'un fichier qui allait dépasser 2 000 lignes. |
