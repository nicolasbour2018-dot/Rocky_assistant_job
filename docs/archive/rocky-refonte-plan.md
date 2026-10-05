# Plan de refonte Rocky — version provisoire

> **Statut : PROVISOIRE** — rédigé le 24 septembre 2026, à affiner lors de la prochaine session.
> Aucune modification applicative n'a encore été faite. Ce document consolide deux audits
> (Codex : `docs/rocky-architecture-audit.md` ; Claude : audit en session) et les décisions
> prises avec Nicolas.

## 1. Pourquoi une refonte

Rocky n'est pas pauvre en fonctionnalités : il en a beaucoup, chacune prudente et testée isolément.
Mais les fondations produisent un outil difficile à vivre au quotidien. Constats principaux,
vérifiés dans le code et sur la base réelle (lecture seule, 24/09/2026) :

| Problème ressenti | Cause racine observée | Repère |
|---|---|---|
| Veille « Data Analyst » invisible hors « Dernière veille » | La requête ponctuelle sert à chercher mais pas à noter : `_localized_profile` → `profile_for_offer` recharge le profil enregistré (Data Scientist). Une offre intitulée « Data Analyst » obtient 43 % sur l'intitulé ; scores 45–59 < seuil 70 | `watch.py`, `repository.py:783-793` |
| APEC fonctionne mal | Recherche sans filtre de lieu ; `description_is_full=False` forcé ; détail APEC bloqué. 648 offres, **6 complètes** ; les incomplètes contournent le seuil | `sources/apec.py:31`, `:82`, `watch.py:219` |
| Pas de « vrai » Indeed | Collecte via TheirStack, 1 page de 20 offres par veille, orientée tech | `sources/indeed.py:185` |
| France Travail absent | Identifiants refusés à chaque veille (problème d'accès côté plateforme, en cours) | table `watch_runs` |
| Mails hors sujet, aucune preuve | Requête Gmail non filtrée (`newer_than:180d`), marqueurs trop larges (« recrutement »), rapprochement employeur par sous-chaîne, confiances constantes, motifs concaténés incohérents. Ex. : digest Quora classé « candidature », alerte LinkedIn classée bruit | `gmail_service.py:65`, `:292`, `:351`, `:787` |
| CV anglais mauvais | Génération par traduction ligne à ligne (code mort) ; en pratique CV EN copié sans ciblage ; CV FR verrouillé par SHA-256 + coordonnées pixels d'un PDF Canva | `profile_documents.py`, `applications.py:105`, `cv_tailoring.py:268` |
| Profils très frictionnants | Activation impossible sans kit anglais ; FR/EN dupliqués ; DOCX à marqueur unique + LibreOffice ; multi-profils + profil actif | `page_profiles.py:628`, `:775` |
| UI chargée | 12 pages ; 3 actions par carte (bouton, popover statut `#id`, expander) ; doubles confirmations ; `load_data()` sans cache exécuté 2 fois par interaction (page + chat flottant) | `dashboard_b.py`, `dashboard_common.py:660` |

Défauts d'intégrité relevés par Codex et confirmés :

- PDF de candidature réécrits au même chemin ; l'historique `application_documents` pointe vers le fichier écrasé.
- Gmail peut changer un statut avant d'enregistrer le message qui le justifie (`email_message_id=None`).
- `revert_application_event` utilise deux transactions (`repository.py:1698-1747`).
- Une veille interrompue peut rester `RUNNING` avec des écritures partielles.
- Offres complètes sous le seuil jetées sans trace.
- Statut porté par `job_offers`, donc partagé entre profils ; aucune migration de schéma.

Dette de code : `repository.py` 2 561 lignes, `job_detail_components.py` 1 227, `page_applications.py` 1 003 ;
le cœur importe `dashboard/job_analysis.py` (dépendance inversée) ; code mort identifié
(`generate_english_documents`, `render_english_cv`, `explain_match`, `stream_chat`,
`stream_llm_response`, `render_ats_report`, `render_ats_v2_report`, `sync_projects`,
`validate_profile_document`, `undo_job_alert_reclassification`…) ; 15 imports inutilisés ;
scripts Hugging Face historiques ; 3 fichiers de tests UI en échec ou bloqués
(`test_dashboard_variants.py`, `test_multi_profile_jobs.py`, `test_application_page_compact.py`).

## 2. Décisions prises

| # | Décision |
|---|---|
| D1 | **Rocky reste multi-utilisateur** : comptes, sessions et SMTP sont conservés (et rangés dans un domaine « Comptes » propre). |
| D2 | **Un compte = un profil.** Suppression de la notion de profil actif, du sélecteur de profil et des profils multiples. |
| D3 | **Recherche multimétier par « pistes »** dans le profil unique (ex. Data Scientist, Data Analyst). Toutes les pistes alimentent la veille ; chaque offre garde la ou les pistes qui l'ont trouvée ; aucun choix ne masque d'offres. |
| D4 | **Les 4 profils de test sont supprimés** (`Nico enseignant test_version`, `GPT test`, `Nouveau profil`, `Hélène`). Seul `Data Scientist` (id 1) est conservé comme profil du compte. |
| D5 | **Les données actuelles sont migrées** (offres, écartées, refus, candidatures, mails) : elles servent de matière à l'analyse de données. |
| D6 | **UI cible : FastAPI + Jinja + HTMX**, validée d'abord par un prototype d'un écran. Plan B : NiceGUI. |
| D7 | **Parcours complet conservé**, réorganisé par étapes métier (pas d'application simpliste). |
| D8 | **France Travail** : accès plateforme en attente ; le connecteur est conservé, désactivable, affiché « en attente d'accès ». La refonte ne dépend pas de cette source. |
| D9 | **Migrations versionnées avec Alembic.** |
| D10 | **Refonte progressive** : Rocky reste utilisable pendant toute la refonte ; chaque nouvel écran remplace une page Streamlit. |
| D12 | **Planification** : un seul déclencheur, le planificateur intégré (usage local Docker). Au démarrage, si la dernière veille date de plus de 24 h, 🏠 Aujourd'hui affiche le retard et propose une veille de rattrapage. Un cron système sera ajouté seulement en cas de déploiement sur un serveur (VPS). |
| D11 | **Sessions persistantes** : un utilisateur connecté le reste (rechargement, favori, URL directe, redémarrage du navigateur) jusqu'à déconnexion ou expiration de la session. |

### Constat du parcours visuel (24/09) : perte de session

Recharger la page ou ouvrir une URL directe (ex. `/page_applications`) renvoie à l'écran de connexion.
Cause : le cookie `rocky_session` est lu via le composant JavaScript `streamlit-cookies-controller`,
dont la valeur n'est disponible qu'après le premier rendu. Au premier passage, la lecture est vide ;
`require_authenticated_user` conclut à l'absence de session et **`_clear_session` supprime le cookie**
(`dashboard/auth_ui.py:31-39`, `:154-172`). La session de 30 jours est donc effacée à chaque rechargement.

- Correctif phase 0 (Streamlit) : lire le cookie côté serveur avec `st.context.cookies` (disponible
  en Streamlit 1.51) ; ne jamais supprimer le cookie quand la lecture est seulement « pas encore
  disponible » ; ne l'effacer que si le serveur a invalidé la session.
- Cible (FastAPI) : cookie de session `HttpOnly`, `Secure` en HTTPS, `SameSite=Lax`, lu à chaque requête,
  avec renouvellement glissant ; option « Rester connecté » sur l'écran de connexion.

### Données liées aux profils de test (constat du 24/09, à traiter en phase 2)

| Table | Profil 1 | Profils de test (2–5) |
|---|---|---|
| `profile_jobs` | 1 079 | 216 liens |
| `job_matches` | 435 | 39 |
| `applications` | 52 | 0 |
| `candidate_skills` | 56 | 9 |
| `watch_runs` | 50 | 3 |

**170 offres ne sont liées qu'à des profils de test.** Proposition à confirmer : les supprimer avec les
profils, sinon elles entreront dans le flux du profil unique.

### Constats du parcours visuel (Chrome, 24/09, consultation uniquement)

| Écran | Constat | Incidence sur le plan |
|---|---|---|
| Cockpit | Le premier écran ne contient aucune action : logo, badge, titre « · V2 », bandeau d'accroche, profil actif. La vue par défaut « Suggestions » affiche **0 résultat** ; les 90 offres sont derrière un autre bouton | 🏠 Aujourd'hui doit s'ouvrir sur du contenu actionnable |
| Tout le flux | Une carte fait environ 430 px de haut (titre, score, entreprise, méta, statut, 3 contrôles) : 90 offres ≈ 45 écrans de défilement. Identifiant interne visible (« Changer le statut · #1193 ») | Mode liste compact + mode tri ; statut en un geste |
| Fiche annonce | « Data Protection Analyst – Freelance » (RGPD) notée **79,6 %** pour un profil Data Scientist : **une seule compétence détectée** (« Gestion des données ») couverte à 100 % → composante compétences pleine malgré un intitulé à 22,7 %. TJM 550 affiché « 550–550 EUR » comme un salaire. Description en bloc de texte non formaté | Matching : pénaliser le manque de preuves (nombre minimal de compétences détectées, confiance du score) ; distinguer TJM et salaire annuel ; mise en forme des descriptions |
| Candidatures | 49 dossiers en **carrousel de 3** (16 clics de flèche) ; dernier dossier le 31/08 | Kanban ou liste dense, filtres par étape |
| E-mails à vérifier | 74 mails, carrousel de 3. Le digest Quora (`french-personalized-digest@quora.com`) est **rattaché à la candidature « French bee – Data Analyst »** : « french » du nom d'entreprise trouvé dans l'adresse Quora. Motif affiché : « employeur de la fiche reconnu dans l'expéditeur » | Confirme le rapprochement par sous-chaîne ; phase 0 (domaine exact) et phase 4 |
| Profil & CV | L'assistant d'onboarding (dépôt de fichiers, analyse) reste affiché en tête alors que les 5 jalons sont validés. Bug d'affichage : les projets apparaissent en dictionnaires Python bruts (`{'title': …, 'description': …}`). Doublons de compétences (« NLP » / « Traitement du langage naturel (NLP) », « Data Visualisation » / « Visualisation de données »). Remarque de l'IA jugeant le parcours de reconversion « très éloigné » | Séparer onboarding et édition ; dédoublonner les compétences (alias canoniques) ; revoir le ton des prompts d'analyse |
| Statistiques | « Taux de réponse 40 % » pour **0 entretien** (accusés de réception comptés comme réponses). Noms de source hétérogènes (`hellowork.com`, `cadremploi.fr`, « Welcome to the J… ») | Dénominateurs explicites (reco Codex) ; normaliser les noms de source |
| Monitoring | Mélange de notes, configuration technique (dépôt du `credentials.json` OAuth), comptes Gmail et historique. **Toutes les veilles affichées sont `PARTIAL`** (France Travail en erreur). Aucune veille du 13/09 au 23/09 : normal (app locale arrêtée), mais rien ne signale ce retard au retour | ⚙️ Système séparé ; source en attente ≠ échec ; retard de veille visible et rattrapage au démarrage (reco Codex n° 5) |
| Session | Recharger une page ou ouvrir une URL directe déconnecte l'utilisateur (voir D11) | Phase 0 |

Les notes de projet saisies par Nicolas dans Monitoring (29–30/08) rejoignent ce plan : storytelling de
préparation de candidature et espace de modification du profil, listes déterministes du CV,
classification de la performance dans les statistiques, résumé de description dans le cockpit,
récupération des informations d'annonce par plateforme (métadonnées, description, résumé, entreprise).

## 3. Parcours cible

```
🏠 Aujourd'hui      → ce qui demande ton attention maintenant
🔎 Offres           → Découvrir & décider
📝 Candidatures     → Préparer → Envoyer → Suivre
📬 Messages         → Retours recruteurs & alertes (avec preuves)
📈 Bilan            → Apprendre de sa recherche (analyse de données)
👤 Profil & kit     → CV maître, pistes, compétences, FR/EN, vérification ATS
⚙️ Système          → Sources, veilles, Gmail, planification, diagnostics
🐾 Rocky (tiroir)   → assistant contextuel disponible partout
```

| Fonctionnalité actuelle | Nouvelle place |
|---|---|
| Cockpit, prochaine action | 🏠 Offres à examiner, dossiers à finir, relances dues, réponses à vérifier, objectif hebdo, résumé depuis la dernière visite |
| Tout le flux, À enrichir, Ajouter une URL, Fiche annonce | 🔎 Mode tri (une offre à la fois, clavier) + mode liste (filtres par piste, sous le seuil, incomplètes). Fiche en panneau latéral avec synthèse de décision (date limite, critères éliminatoires, preuves du profil, manques) |
| Préparer une candidature, Candidatures | 📝 Kanban. Dossier en 4 étapes : CV ciblé → lettre/message → envoi (préremplissage, confirmation avec date et canal) → suivi (chronologie, notes, prochaine action datée) |
| Tri Gmail | 📬 Flux avec règle déclenchée, extrait justificatif, auteur ; correction = nouvelle règle |
| Statistiques | 📈 Entonnoir à dénominateurs explicites (accusé ≠ réponse humaine ≠ entretien), par source, piste, langue |
| Profil & CV, ATS V3 | 👤 Profil unique ; ATS V3 devient « Vérifier mon CV » |
| Monitoring, veilles, OAuth | ⚙️ État lisible par source |
| Assistant, chat flottant | 🐾 Tiroir chargé à l'ouverture seulement |

Règles de conception : une action principale par écran ; changement de statut en un geste ;
confirmation uniquement pour l'irréversible ; explications derrière un « Pourquoi ? » ;
vocabulaire unique ; états vides explicatifs.

## 4. Architecture cible

- **Hexagonale progressive** (recommandation Codex) : cas d'usage extraits parcours par parcours,
  pas de réécriture globale en couches abstraites.
- Cas d'usage : `Comptes`, `Veille`, `TriOffres`, `DossierCandidature`, `TriMessages`, `Bilan`.
- Adaptateurs : sources d'offres, Gmail (lecture seule), SQL par domaine, fichiers PDF, navigateur (préremplissage), LLM (Groq).
- Web : routes FastAPI → cas d'usage → fragments HTML (HTMX).
- Conservés : matching déterministe et explicable, dataclasses, contrat `JobSource`, « Rocky ne postule jamais ».

### Modèle de données (esquisse)

- `accounts` (existant) 1—1 `profile` (+ localisations FR/EN) 1—n `search_tracks` (pistes).
- `job_offers` : faits de l'annonce uniquement ; lien vers les pistes qui l'ont trouvée.
- `job_decisions` : valeur (à examiner, intéressé, écarté, plus tard), raison, auteur (`user`, `rule`, `ai`, `migration`), date.
- Indicateurs calculés (incomplète, ancienne, sous le seuil) au lieu de statuts.
- `applications` : étapes, prochaine action datée, révisions immuables de documents (chemin + hash).
- `email_messages` : classification, règle, extrait justificatif, auteur, corrections.
- `events` : journal en ajout seul de toutes les décisions et transitions.
- `match_scores` : score + détail + **version des règles de score**.

### Analyse de données (objectif de D5)

- Conserver les offres sous le seuil (exemples négatifs) et les raisons de rejet.
- Requalifier les 869 « ÉCARTÉE » sans deviner : `auto:ancienneté` / `user` / `inconnu`, marquées `source=migration` avec la règle appliquée.
- Corrections Gmail conservées comme jeu étiqueté.
- Vues `analytics_*` (entonnoir, décisions par raison, performance par source, piste et langue) et export Parquet pour notebook.
- Sauvegarde complète avant migration ; migration rejouée d'abord sur une copie.

## 5. Plan d'actions

| Phase | Contenu | Critère de sortie | Effort indicatif |
|---|---|---|---|
| **0. Stabiliser** (dans Streamlit) | Corriger la notation des veilles ponctuelles. **Sessions persistantes (D11)**. Intégrité : PDF versionnés, message Gmail persisté avant décision (même transaction), annulation en une transaction, veille toujours close. Sources/Gmail : filtre de lieu et pré-filtre d'intitulé APEC, requête Gmail `-category:promotions -category:social`, marqueurs corrigés (alertes LinkedIn/Indeed par expéditeur, retrait de « recrutement »). France Travail « en attente d'accès ». Activation du profil sans kit anglais | Une veille « data analyst » est visible dans toutes les vues ; une panne simulée ne laisse aucun état contradictoire | 2–3 j |
| **1. Nettoyage** | Code mort, scripts HF, imports ; `job_analysis` dans le cœur ; fonctions pures du cockpit extraites ; 3 tests UI réparés ; ruff + vérificateur de types ; documentation et règles alignées | Suite verte en moins de 2 min | 1–2 j |
| **2. Modèle et migration** | Alembic ; profil unique + pistes ; suppression des profils de test (D4) ; journal d'événements ; décisions avec auteur/raison ; versions de score ; migration traçable ; vues `analytics_*` et export Parquet | Migration rejouée sur copie ; comptes cohérents (offres, 52 candidatures, 806 mails) ; aucune perte non voulue | 4–5 j |
| **3. Cœur métier** | Cas d'usage testables sans Streamlit, SQL ni Gmail ; domaine Comptes sans SQL dans `AuthService` | Chaque cas d'usage testé avec de faux adaptateurs | 3–5 j |
| **4. Offres et messages** | Mails d'alerte comme source (Indeed, APEC, LinkedIn, WTTJ, Hellowork, Cadremploi) ; Gmail en 3 étages (expéditeur → domaine exact employeur → LLM pour l'ambigu) avec preuve ; corrections → règles ; France Travail prêt à brancher | Au moins une offre Indeed réelle par jour ; 100 % des décisions Gmail avec preuve lisible | 3–4 j |
| **5. CV et lettre** | CV maître structuré FR/EN ; gabarit HTML/CSS → PDF (Playwright) ; ciblage par sélection et ordre ; traduction champ par champ avec glossaire et validation ; lettre par le même moteur ; fin du verrou Canva et de LibreOffice | CV anglais ciblé sans ressaisie | 3–5 j |
| **6. UI FastAPI + HTMX** | Prototype du tri des offres, puis remplacement écran par écran | Une action principale claire par écran ; parcours vérifiés visuellement | 8–12 j |
| **7. Motivation et analyse** | Objectif hebdo, série, résumé depuis la dernière visite ; 📈 Bilan branché sur les vues d'analyse | Ce qui marche est visible par source, piste et langue | 2–3 j |

## 6. À affiner lors de la prochaine session

1. Confirmer la suppression des **170 offres** liées uniquement aux profils de test.
2. Détailler le modèle de données (tables, colonnes, règles de requalification des écartées) avant d'écrire la première migration Alembic.
3. Définir les **pistes** : champs (intitulés, mots-clés, lieux, seuil propre ?), et la manière dont le score les utilise.
4. Choisir le périmètre exact de la phase 0 et son ordre (proposition : bug de notation → intégrité → Gmail → APEC).
5. Préciser les indicateurs d'analyse attendus (questions auxquelles le Bilan doit répondre).
6. Gabarit de CV : structure du CV maître, rendu visuel souhaité, règles de ciblage.
7. Prototype HTMX : écran de tri des offres, pour valider la technologie et la prise en main.
8. Mettre à jour `AGENTS.md` (écritures autorisées) avant la phase d'implémentation.
9. Matching : règle de « preuve minimale » (une offre avec 1 compétence détectée ne peut pas obtenir la composante compétences pleine) ; afficher une confiance du score ; distinguer TJM et salaire.
10. Planification : décidée (D12). Reste à préciser le seuil exact du rattrapage et le retrait de `cron/rocky.cron.example` de la documentation active.
