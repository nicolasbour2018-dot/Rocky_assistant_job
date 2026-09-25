# B5 — Profil et pistes

Date : 25/09/2026 · Étape : B5 (plan v2) · Préparation : *grill me* puis mode plan

Critère de sortie : « Profil réimporté sans doublons ; au moins 2 pistes définies. »

## Décisions métier (grill me avec Nicolas, 25/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Contenu du profil | Le profil stocke **tous les faits** : identité, accroche, expériences et formations, projets, compétences, langues, préférences, pistes. D2 ajoute la sélection, l'ordre et le rendu du CV. |
| Q2 | Catalogue de compétences | **Propre à chaque compte** (un mécanicien n'a que faire des compétences data). Un compte neuf démarre sans compétence : l'amorçage de 22 compétences data de l'ancien Rocky n'est pas repris. |
| Q3 | Contenu d'une piste | Nom, intitulés, mots-clés, mots exclus, lieux. Contrat, télétravail, salaire et TJM sont au niveau du profil, communs à toutes les pistes. |
| Q4, Q27 | Onboarding | Parcours guidé en 3 écrans (identité → compétences → première piste) à `/profil/demarrage`. Tant que le profil n'est pas prêt, les pages principales y renvoient ; « Plus tard » mène à 👤 Profil & kit, où un bandeau rappelle ce qui manque. **Profil prêt** : une piste active avec au moins un intitulé et un lieu ; l'onboarding disparaît alors définitivement. L'anglais n'est jamais requis. |
| Q5 | Journal | Seulement les faits qui expliquent un changement de score ou de veille : profil importé, onboarding terminé, piste créée, modifiée, mise en pause, reprise, archivée ou supprimée, compétence ajoutée, modifiée ou retirée, préférences modifiées. Pas les corrections de texte (accroche, puces). |
| Q6 | FR / EN | Une seule entité par fait, textes FR (obligatoire) et EN (facultatif) ; les données neutres (dates, stack, niveau) une seule fois. Un texte EN vide ne bloque rien ; D3 le remplira par traduction. |
| Q7 | Compétence | Libellé FR, libellé EN facultatif, alias, niveau (débutant, intermédiaire, avancé, expert ; facultatif), catégorie (technique, métier, savoir-être), drapeau « clé ». Pas d'années d'expérience (peu fiables, jamais utilisées par le score). |
| Q8 | Langues | Rubrique séparée, niveau CECR A1–C2 ou langue maternelle. « Anglais (C1) » et « Espagnol (B2) » sortent des compétences au réimport ; le français est ajouté en langue maternelle. |
| Q9 | Doublons | Libellés FR, EN et alias sont **uniques ensemble** dans un compte, après normalisation (casse, accents, ponctuation). Un ajout en conflit est refusé : « déjà présent sous X ». |
| Q10, Q17 | Réimport | En deux temps : un script de procédure lit les CSV de l'archive et écrit un **fichier JSON hors du dépôt** (données personnelles) ; Nicolas le relit ; `rocky-admin import-profil` l'importe dans son **compte d'essai** de la base de développement. Le même fichier servira au compte réel à la bascule (F2). Réservé à ce réimport : un nouvel utilisateur passe par l'onboarding. |
| Q11 | Fusions | « Traitement du langage naturel (NLP) » fusionnée dans « NLP », « Visualisation de données » dans « Data Visualisation » : le libellé perdant devient un alias. Les paires proches (Modélisation / Modélisation prédictive ; Analyse de données / EDA / Analyse statistique) restent distinctes. |
| Q12 | Domaines cibles | Plus de champ « domaines » : le fichier d'import les montre pour que Nicolas les place en mots-clés de piste ou les abandonne. |
| Q13, Q19 | Expériences et formations | L'archive n'en a que 7 phrases libres produites par le LLM. Claude préremplit des brouillons dans le fichier d'import à partir du CV FR de l'archive ; Nicolas les relit. Aucun appel LLM dans Rocky en B5. |
| Q14 | Documents | Aucun CV ni lettre réimporté ; la section « Kit » annonce D2. |
| Q15 | Pistes de Nicolas | Créées par Nicolas lui-même dans l'interface (point de départ : « Data scientist / IA » et « Data analyst »). |
| Q16 | Écran 👤 Profil & kit | Une page à sections : Pistes, Compétences, Langues, Expériences & formations, Projets (**facultatif** : tout le monde n'a pas de projets), Identité & préférences, Kit. Lecture d'abord, édition sur place, bascule FR / EN par section. |
| Q20 | Lieux d'une piste | Libellés libres jusqu'à C6 ; lieux structurés (ville + rayon, région, pays) visés pour la version finale, à revoir après C6. |
| Q21 | Cycle de vie d'une piste | Active, en pause (n'alimente plus la veille) ou archivée (masquée, conservée). Suppression définitive seulement tant qu'aucune offre n'y est rattachée (toujours le cas en B5 ; la garde arrive avec le rattachement en C6). |
| Q22 | Préférences | Contrats (CDI, CDD, freelance, VIE, stage, alternance, intérim), télétravail (sur site, hybride, complet), salaire annuel brut minimal (€), **TJM minimal (€/jour HT)** — des pistes freelance sont prévues. Tous facultatifs. |
| Q23 | Identité | Nom obligatoire, le reste facultatif ; e-mail de contact distinct du compte (prérempli avec lui) ; ville et code postal, pas d'adresse complète ; accroche FR / EN. |
| Q24 | Import d'un CV PDF | Pas en B5 (adaptateur LLM, lecture PDF, relecture des propositions). Option ajoutée plus tard à l'onboarding, rattachée à D2 qui lit déjà les PDF. Le LLM de Rocky passera à Gemini 3.5 Flash Lite. |
| Q25 | Langue des intitulés | Intitulés et mots-clés d'une piste : une liste unique, en n'importe quelle langue (ce sont des chaînes de recherche). Le nom de la piste n'est pas traduit. |
| Q26 | Parcours et projets | **Expérience / formation** : type, intitulé FR / EN, organisme, lieu, début et fin au mois (fin vide = en cours), puces FR / EN, compétences liées. **Projet** : nom, problème, réalisation, résultats (FR / EN), stack, lien, compétences liées. Les compétences liées pointent vers les compétences du profil (preuves pour C7, caractéristiques possibles pour C4). |

Remarques de Nicolas consignées pour la suite (section 8 du plan) : le CV régénéré garde le design du CV actuel
(gabarit HTML/CSS qui le reproduit) et ne doit **jamais dériver** d'une génération à l'autre (D2, D5).

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme du module | `rocky/profil/` : `model.py` (dataclasses, codes, port `ProfileStore`), `rules.py` (pur), `usecases.py` (`ProfileEditor`), `sql.py`, `import_file.py`, `web.py`, `templates/profil/` | Même forme que `rocky/system/auth/`. |
| Unicité des compétences | Table `skill_terms (profile_id, term)` en clé primaire : chaque terme normalisé (libellé FR, EN, alias) d'une compétence y figure une fois. Le cas d'usage refuse le conflit avec un message ; la base le refuse de toute façon | « Sans doublons » garanti par PostgreSQL, pas seulement par l'écran. |
| Codes stockés | Anglais : contrats `permanent`, `fixed_term`, `freelance`, `international_volunteer`, `internship`, `apprenticeship`, `temporary` ; télétravail `on_site`, `hybrid`, `full_remote` ; niveaux `beginner`… `expert` ; catégories `technical`, `business`, `soft` ; langues ISO 639-1 et `a1`…`c2`, `native` | Règle B4 : codes anglais dans les données, libellés français à l'écran. |
| Listes | Colonnes `text[]` (intitulés, mots-clés, lieux, alias, puces, stack) ; saisie « une par ligne » | Pas de table par liste sans besoin (règle d'architecture). |
| Porte d'onboarding | Middleware de `profil` sur les seules adresses des entrées de navigation (`/`, `/offres`…), jamais sur `/profil`, les fragments, les pages de compte ni les fichiers statiques ; il est ajouté **avant** celui des sessions, donc s'exécute après lui | Une requête par page principale ; aucune route existante n'est modifiée. |
| « Plus tard » | Date `onboarding_deferred_at` : la porte ne renvoie plus vers l'onboarding, le bandeau de 👤 reste jusqu'au profil prêt | Pas d'insistance, mais le manque reste visible. |
| Fichier d'import | JSON versionné (`"format": "rocky-profil/1"`), validé champ par champ avec le chemin de l'erreur ; les compétences liées sont désignées par leur libellé ou un alias ; une rubrique `a_relire` non vide fait **refuser** l'import (relecture humaine obligatoire) | Erreurs lisibles, aucune donnée devinée. |
| Import | Une transaction ; refusé si le profil a déjà un contenu (nom, compétence, langue, parcours, projet ou piste) : un second lancement ne change rien | Idempotence, critère « sans doublons ». |
| `rocky-admin` | Devient une racine de composition (`rocky/system/admin.py`) : `invite` (`system/auth`) et `import-profil` (`profil`) ; l'adresse est résolue par l'accès SQL des comptes | Seul `auth/sql.py` lit les comptes. |
| Confirmation | Suppressions (piste, compétence, langue, expérience, projet) confirmées par un second bouton dans un `<details>`, sans boîte de dialogue du navigateur | Confirmation réservée à l'irréversible ; marche sans JavaScript. |
| Dépendances | Aucune nouvelle dépendance ; le script de procédure n'utilise que `csv` et `json` | Parquet demanderait `pyarrow`. |

## Mesures

### Mesures de Claude (25/09/2026)

| Contrôle | Résultat |
|---|---|
| Vérification globale | `docker compose run --rm --build check` vert : 234 tests en 8,7 s (36 s au total) ; ruff, mypy strict |
| Migration `0003` | `compare_metadata` vide ; `upgrade` / `downgrade` sur base vide ; sur la base de développement : `upgrade head`, `downgrade -1`, `upgrade head` → `0003 (head)` |
| Doublons refusés par la base | test SQL : un second terme identique dans `skill_terms` et le lien vers la compétence d'un autre profil lèvent `IntegrityError` |
| Extraction de l'archive | 56 compétences → 52 (2 fusions, 2 langues) ; 3 langues ; 4 projets ; 7 brouillons d'expériences et formations tirés du CV ; 17 éléments à relire |
| Répétition du réimport (schéma jetable de `test-db`) | 52 compétences, 0 libellé en double, 72 termes uniques, alias de NLP repris, 14 liens d'expériences et 8 de projets, un événement `profil.profile_imported` ; **second lancement : « rien n'a été importé »** |
| Navigateur (Chromium, Playwright, instance à part) | compte neuf → activation → démarrage guidé en 3 étapes (erreur « au moins un intitulé et un lieu » affichée, saisie conservée) → 👤 sans bandeau ; édition d'une piste sur place, « Annuler » puis « Modifier » à nouveau, enregistrement sans rechargement ; conflit « déjà présent sous « NLP » » affiché sur place ; console sans erreur. Captures d'écran impossibles (délai dépassé par l'outil) : l'aspect visuel reste à juger par Nicolas |

Constat soumis à Nicolas : « traitement du langage naturel » (sans « (NLP) ») n'est pas reconnu comme un nom de
« NLP » dont l'alias est « Traitement du langage naturel (NLP) » : Q9 compare les noms entiers.

### Validation de Nicolas (25/09/2026)

Nicolas a relu le fichier, l'a importé dans son compte d'essai et a créé ses pistes. Mesure sur la base de
développement (lecture seule) : **52 compétences, 0 libellé en double, 72 termes uniques, 2 pistes actives prêtes**
(intitulé et lieu), 7 expériences et formations, 4 projets, un seul `profil.profile_imported`. Critère de sortie tenu.

Retour sur l'écran : « Le reste me plaît beaucoup. » Deux ajustements demandés et faits avant la clôture :

| Demande | Réalisation |
|---|---|
| Compétences trop chargées : garder les catégories, 5 compétences par catégorie et le reste dans un dépliant | 5 compétences au plus par catégorie, clés en premier, qui passent à la ligne ; les autres dans « Tout afficher (+N) » (élément `details` natif, sans JavaScript), déplié si la compétence en cours d'édition s'y trouve. Première version mal comprise (toutes les compétences forcées sur une ligne visuelle : défilement latéral) corrigée à la demande de Nicolas |
| Cacher les alias à l'affichage : procédure interne | Alias absents de la liste ; dans le formulaire d'édition, repliés sous « Autres noms (alias) · N », dépliés seulement après un refus |

Question laissée ouverte (sans réponse de Nicolas, règle Q9 inchangée) : faire répondre « X (Y) » aussi à X et à Y.
Notée en section 8 pour C3, où la détection dans les annonces la rendra utile ou non.
