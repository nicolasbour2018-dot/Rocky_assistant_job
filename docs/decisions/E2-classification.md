# E2 — Classification des messages

Date : 04/10/2026 · Étape : E2 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q18) puis mode plan

Critère de sortie (plan) : « 100 % des décisions ont une preuve lisible ; le digest Quora n'est plus rattaché à
"French bee" ; jeu de test issu de l'archive ».

## Constats de départ

| Constat | Source |
|---|---|
| L'ancien classifieur ne lit que l'objet et l'extrait ; marqueurs pris dans l'ordre (offre, refus, test, entretien, accusé, en cours), puis alertes, puis « candidature » au sens large ; **aucun LLM** | `dashboard/rocky/gmail_service.py` (l. 60-210), tag `rocky-v1-streamlit` |
| L'expéditeur ne classe rien : il sert seulement à reconnaître l'employeur, **par sous-chaîne** d'un jeton du nom. « french » est trouvé dans `french-personalized-digest@quora.com` (digest Quora → « French bee ») ; le jeton « de » de « Ministère **de** la justice » est trouvé chez METRO, dont le **refus a été appliqué** à cette candidature ; « le » de « Choisir **le** Service Public » rattache Google Agenda et OVH | `match_application` (l. 260-324), archive `email_messages` (id 144, 710, 800, 876…) |
| Confiances constantes par catégorie (0,99 / 0,98 / 0,97 / 0,96 / 0,94 / 0,92 / 0,78) ; application automatique au-dessus de 0,95 | `gmail_service.py` (l. 38-39, 118-210) |
| Archive : 841 messages, 2 boîtes, du 21/08 au 24/09, **sans corps** (extrait Gmail ≤ 200 caractères). NOISE 600, JOB_ALERT 140, APPLICATION_UPDATE 90, accusés 7, en cours 3, refus 1 ; aucun entretien ni offre. 85 des 100 alertes de `jobalerts-noreply@linkedin.com` classées en bruit | `backups/rocky-v1-20260924/exports/csv/email_messages.csv` |
| Les 66 corrections de l'archive ne sont pas des étiquettes fiables : des refus (COVEA, Talan) y sont marqués « bruit » (geste « Ignorer » de l'ancien écran) | archive, id 531, 638 |
| Les plateformes sont des **relais** : une même adresse envoie alertes, accusés de la plateforme et réponses d'employeurs (`jobs-noreply@linkedin.com`, `emploi@emails.hellowork.com`, `noreply@indeed.com`, `*@reply.hellowork.com`) | archive, expéditeurs des plateformes |
| Les réponses d'employeurs arrivent surtout par des **ATS** : Ashby, Greenhouse, SmartRecruiters (`notification@smartrecruiters.talan.com`), join.com, beetween, Digital Recruiters, Recruitee, jobs2web, `talent.metro.de` | archive |
| Le nouveau Rocky ne connaît **pas le domaine des employeurs** (`company`, `url`, `application_url`) ; dans l'archive, les liens des offres sont presque tous des sites d'emploi (Adzuna, LinkedIn, WTTJ, Apec, Indeed) : le domaine déduit des liens ne servira que rarement | `rocky/offres/model.py` (`OfferHeading`), archive `applications.csv` |
| E1 laisse un seul point d'entrée, le crochet `app.state.messages_collected`, et des messages déjà enregistrés sans décision | `rocky/messages/web.py`, plan §8 (E1 → E2) |

## Décisions métier (grill avec Nicolas, 04/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Frontière avec E4 | E2 écrit une **décision par message** : catégorie, candidature rattachée (ou aucune), niveau de confiance, preuve (étage, règle, extrait, auteur, version). **Aucun statut de candidature ne change** : les transitions sont l'affaire d'E4. |
| Q2 | Catégories | `acknowledgement` Accusé de réception · `rejection` Refus · `interview` Entretien · `assessment` Test ou cas pratique · `offer` Offre · `employer_update` Autre message de l'employeur (dossier en cours, offre retirée, question) · `recruiter_approach` Approche d'un recruteur · `job_alert` Alerte emploi · `unrelated` Hors recherche. Ce qu'aucune règle ni le modèle ne tranche n'a **pas** de catégorie : « À vérifier », avec sa raison. Étape proposée pour E4 : refus → Refusée ; entretien, test → Entretien ; offre → Offre ; autre message → En discussion ; les autres, aucune. |
| Q3 | Domaine de l'employeur | Déduit des liens de l'offre (`application_url`, `url`) quand ce n'est ni un site d'emploi ni un ATS ; **saisi** dans le dossier (facultatif) ; appris des corrections en E4. Expéditeur ATS ou plateforme : **nom complet de l'entreprise, entre limites de mots**, dans le nom affiché ou l'objet. Jamais un mot isolé. |
| Q4 | Confiance | **Trois niveaux** (haute, moyenne, faible), chacun avec ses raisons affichées ; pas de nombre. |
| Q5 | Messages vus par le LLM | Seulement ceux qui portent un **signal de recherche d'emploi** (Q17). Les autres sont `unrelated` par règle, preuve « aucun signal de recherche d'emploi ». |
| Q6 | Règles par expéditeur | Dans le code, versionnées (`CLASSIFY_VERSION`). Les règles par compte, nées des corrections, viennent en E4. |
| Q7 | Jeu de test | Échantillon de l'archive anonymisé et **étiqueté par Nicolas** (`tests/messages/data/archive_sample.csv`), cas imposés compris (Quora / French bee, METRO / Ministère, alertes LinkedIn en bruit, OVH / Choisir le Service Public, bruit de la recette d'E1), plus quelques messages récents de la base de développement, anonymisés, avec leur corps. |
| Q8 | Intention | **Phrases explicites** par règle (sans accents, objet et corps, limites de mots). Employeur reconnu sans phrase, ou phrases contradictoires → LLM. Les phrases ambiguës (« after careful consideration », aussi dans les accusés) sont retirées ou ne comptent qu'en appui. |
| Q9 | Niveaux | **Haute** : règle d'expéditeur (adresse d'alerte, adresse hors recherche connue) ; phrase d'intention et candidature par domaine exact ou par le fil. **Moyenne** : phrase et nom exact via un ATS ou une plateforme ; LLM à l'extrait vérifié dont la candidature concorde avec les règles ; `unrelated` faute de signal (déduit d'une absence). **Faible** : LLM seul ; signaux contradictoires non résolus. |
| Q10 | Seuils | En E2 : faible → « À vérifier » ; moyenne et haute → décidé, avec « Pourquoi ? ». Orientation pour E4, re-décidée à son grill : une transition sans confirmation seulement au niveau haut, et seulement pour refus, entretien, test, offre. |
| Q11 | Candidatures possibles | Celles qui sont **Préremplie** ou plus loin, issues comprises (Refusée, Sans réponse, Retirée) ; jamais En préparation ni Prête à envoyer. **Règle du fil** : un message du même fil Gmail qu'un message rattaché hérite de sa candidature. Deux candidatures chez le même employeur : intitulé exact dans l'objet ou le corps, sinon LLM sur ces seules candidatures, sinon faible, « plusieurs candidatures possibles », aucun choix arbitraire. |
| Q12 | Contrat du LLM | Entrée : expéditeur, objet, date, corps texte coupé à 8 000 caractères, candidatures possibles (entreprise, intitulé, date d'envoi, identifiant opaque), définitions des catégories. Sortie (schéma JSON validé) : catégorie (une des 9 ou `unknown`), candidature (identifiant de la liste ou rien), extrait **mot pour mot**, raison en une phrase. Extrait introuvable dans le message ou identifiant hors liste → réponse refusée, « À vérifier ». Panne (clé absente, délai, quota) → **aucune décision** : le message reste « en attente de classement » avec la raison, repris au passage suivant. Le modèle classe et cite ; il n'invente ni date ni action. |
| Q13 | Reclassement | Décisions en **ajout seul** ; la décision en vigueur est la dernière. Reclassement **à la demande** seulement, jamais au démarrage (coût des appels), sans jamais écraser une décision de l'utilisateur (E4). |
| Q14 | Écran | 📬 Messages : « Messages triés » — date, boîte, expéditeur, objet, catégorie, candidature (lien vers le dossier), niveau ; « Pourquoi ? » (étage, règle ou modèle, extrait, version, recherche d'origine). Filtres : À vérifier · Retours d'employeurs · Alertes · Approches · Hors recherche · Tous ; par défaut Retours d'employeurs et À vérifier. Compteur « n en attente de classement » avec la raison. Aucune correction (E4). |
| Q15 | Appels réels | Accordés pour la mesure, **200 au plus en tout**, sans abus. |
| Q16 | Plateformes | À l'**adresse exacte**, jamais au domaine seul. (1) Adresses d'alerte pures → `job_alert`, haute. (2) Adresses relais → motifs d'objet : « candidature envoyée à X », « arrivée chez X », « transmise à X » → accusé, candidature X par nom exact ; « X recrute » → alerte ; « réponse de X », « des nouvelles de votre candidature pour X », `reply.hellowork.com` → message de l'employeur X (phrases, sinon LLM) ; « code de vérification », « Bienvenue », « Complétez vos informations » → `unrelated` ; sinon le chemin commun. (3) Autres adresses des plateformes (`messages-noreply@`, `invitations@`, `security-noreply@`, `billing-noreply@`… chez LinkedIn) → `unrelated`, haute. Risque connu : une InMail arrivée par `messages-noreply@` (E4). |
| Q17 | Signaux de recherche | Expéditeur ATS connu, ou domaine exact d'un employeur candidaté ; nom exact d'une entreprise candidatée dans le nom affiché ou l'objet (pas le corps) ; **expression** de candidature dans l'objet ou les 2 000 premiers caractères du corps (« votre candidature », « your application », « entretien », « interview », « processus de recrutement », « suite à votre candidature »…), jamais un mot isolé. Mesurés sur l'archive avant d'être figés. |
| Q18 | Plafonds | Par compte : **20 appels par passage, 60 par jour**, modifiables par configuration. Au-delà : « en attente (plafond du jour atteint) ». Une ligne par appel en base. La reprise des messages déjà collectés passe par les mêmes règles et plafonds. Mesure en deux temps : règles seules, puis LLM borné. |


### Affinage après le premier essai (Nicolas, 05/10)

Constats sur sa boîte : la vue par défaut montrait 92 messages, dont 62 accusés de réception (36 « Votre candidature
est arrivée chez… » de Hellowork) ; « Message de l'employeur » ne contenait que des rappels de Hellowork ; aucun message
n'était rattaché, ses candidatures faites hors de Rocky n'y existant pas. Une vue « À vérifier » sans geste ne sert à
rien : les corrections sont l'objet d'E4, avancée avant E3.

| # | Sujet | Décision |
|---|---|---|
| Q19 | Vue par défaut | « À regarder » = ce qui demande une lecture ou une action : refus, entretiens, tests, offres, messages d'employeurs, approches, avis de plateforme qui demandent une action, « À vérifier », messages en attente. Les accusés de réception ont leur vue « Accusés » et un compteur en tête. |
| Q20 | Avis des plateformes | 10ᵉ catégorie `platform_notice` « Avis de plateforme » (candidature à finaliser, offre retirée, candidature vue, rappels) ; « Message de l'employeur » ne garde que ce qu'écrit l'employeur. « Finalisez votre candidature sur le site de… » reste dans la vue par défaut (règle `relay.to_finish`). |
| Q21 | Doublons d'une candidature | Regroupement par candidature en E4 (« ce qui a bougé »), qui dépend du rattachement. |
| Q22 | Candidatures inconnues de Rocky | L'employeur que nomme la plateforme est gardé dans la preuve, tel qu'écrit (règle `employer.cited`), pour qu'E4 retrouve ou crée la candidature. |
| — | Ordre des étapes | **E4 avant E3** (Nicolas, 05/10) : les corrections et transitions d'abord, les alertes comme source ensuite. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme du code | Sous-paquet `rocky/messages/classification/` : `model.py` (catégories, niveaux, étages, preuves, ports), `rules.py` (règles pures), `llm.py` (consignes, schéma, vérification de la réponse), `usecases.py` (passage de classement). SQL dans `rocky/messages/sql.py` | Même forme que `offres/analysis` et `offres/scoring` |
| Deux axes | `classify` rend une `Verdict` (catégorie, candidature, niveau, preuves) ou un `Pending` (ce que les règles ont trouvé, pour le modèle). La catégorie vient des phrases ou des formes d'objet des plateformes ; la candidature du fil, du domaine, du nom ou de l'intitulé | La v1 confondait « employeur reconnu » et « catégorie » (`APPLICATION_UPDATE`) |
| Comparaisons | Forme pliée de l'analyse (`offres.analysis.text.fold` : sans casse ni accents, ponctuation en espaces), **mots entiers** ; domaine **enregistrable** (`talent.metro.de` → `metro.de`, `x.finances.gouv.fr` → `finances.gouv.fr`) comparé à l'égalité ; nom de l'employeur entier, aussi sans forme juridique (`SARL`, `SAS`, `S.L.`…), 3 caractères au moins | Fin des sous-chaînes (Quora, METRO, « le », « de ») |
| Intitulé de l'offre (affinement de Q9) | Un rattachement par le **nom** sans l'intitulé de l'offre dans le message est **« À vérifier »** (faible) ; par le **domaine**, il reste moyen. L'intitulé est retrouvé tel quel, ou par 60 % de ses mots (hors H/F, CDI, junior…). Seul, un intitulé ne rattache qu'à partir de 3 mots et s'il est unique | Talan (archive 418) : la seule candidature chez Talan n'était pas le poste du message |
| Phrases | Décisives (refus, entretien, test, offre) ; de courtoisie (accusé, dossier en cours), qui ne comptent qu'en l'absence de décisive. Deux décisives différentes → modèle. Un refus **au conditionnel** (« sans retour de notre part… », « si vous ne recevez pas… ») ne compte pas | Un refus commence souvent par « nous avons bien reçu » ; Expleo et Devoteam accusent réception avec un refus conditionnel |
| Plateformes | À l'adresse exacte (`ALERT_SENDERS`, `RELAY_SENDERS`, `UNRELATED_SENDERS`) ; une forme d'objet reconnue d'un relais **l'emporte** sur les phrases du corps ; le nom affiché d'un relais (« Hellowork ») ne désigne jamais l'employeur ; les avis d'une plateforme ne forment pas une conversation (pas de règle du fil) | Le corps d'un avis Hellowork contient les réponses d'un questionnaire (« Non, ma candidature n'a pas été retenue ») ; Gmail regroupe ses avis par objet |
| Corps lu | Le corps texte est lu **décodé** (`rules.readable`) quand il contient des entités HTML ; le message enregistré n'est jamais modifié | Talan, Sopra Steria : « Nous avons bien re&ccedil;u votre candidature » |
| Schéma | `message_decisions` en ajout seul (catégorie nulle = « À vérifier », niveau, auteur, règle et extrait de la première preuve, preuves en JSONB, version, date) avec contraintes : règle et extrait non vides, au moins une preuve, rien de décidé → niveau faible. `mail_model_calls` : une ligne par appel (issue acceptée / refusée / échouée, raison, durée). `application_domains` (module `candidatures`) en ajout seul. Migration `0014` | Le critère « 100 % des décisions ont une preuve » est porté par le schéma |
| Passage | `classify_messages` : verrou consultatif par compte ; lit **tous** les messages sans décision par lots de 500 (ou tous, pour reclasser), décide par les règles, puis appelle le modèle sur les messages en attente, les plus récents d'abord. Une décision par transaction, avec son événement `messages.message_classified` (acteur `rule` ou `ai`) et la ligne de l'appel ; un message décidé entre-temps n'est pas décidé deux fois. Premier échec du modèle : aucune décision, fin des appels du passage | Q12, Q13 ; le crochet d'E1 et la reprise des messages sans décision sont le même chemin |
| Plafonds (Q18) | **20 appels sur l'heure glissante, 60 sur 24 h**, par compte (`ROCKY_LLM_MAIL_HOUR_LIMIT`, `ROCKY_LLM_MAIL_DAY_LIMIT`), comptés en base ; `--limite` borne un passage | « Par passage » devient « par heure » : un passage suit chaque collecte de chaque boîte |
| Modèle | Identifiants opaques (`C1`, `C2`) ; corps coupé à 8 000 caractères ; citation vérifiée sans casse, accents ni espaces, 12 caractères pliés au moins ; une réponse refusée garde la citation du modèle dans sa preuve. Sans clé Gemini : aucun appel, messages « en attente » avec la raison | Q12 ; diagnostic des refus |
| Reclassement | `rocky-admin messages-classer <email> --reclasser` ajoute une décision par message (jamais par-dessus une décision de l'utilisateur) ; un message que les nouvelles règles laissent au modèle garde sa décision précédente jusqu'à la réponse du modèle | Q13 ; aucun appel au démarrage |
| Écran | Liste triée (50 derniers messages de la vue), vues `?vue=` (À regarder, À vérifier, Retours d'employeurs, Accusés, Avis de plateforme, Alertes, Approches, Hors recherche, En attente, Tous) ; « Pourquoi ? » en `<details>` ; lien vers le dossier. Domaine de l'employeur dans l'étape « Suivi » du dossier (`/candidatures/{id}/domaine`) | Q14, Q19, Q3 |
| Avis de plateforme (Q20) | Catégorie ajoutée par la migration `0015` (contrainte élargie ; le retour arrière remet ces décisions en « Message de l'employeur ») ; règles `relay.to_finish` (Finalisez, problème d'envoi : dans la vue par défaut, `ACTION_RULES`), `relay.reminder`, `relay.closed`, `relay.seen`, `relay.withdrawn` | Une migration commitée ne se modifie pas |
| Commandes | `rocky-admin messages-classer <email> [--sans-llm] [--limite N] [--reclasser]`. `rocky-admin messages` reste une collecte seule : la classification suit dans l'application, ou par `messages-classer` | Pas d'appel au modèle caché dans une commande de collecte |
| Jeu de test (Q7) | `tests/messages/data/archive_sample.csv` (92 messages) et `archive_applications.csv` ; les messages récents de la base de développement sont reproduits **anonymisés et réécrits** dans les tests des règles (Devoteam, Hellowork, Talan, Team.is), pas copiés tels quels | Aucune donnée personnelle brute dans le dépôt |

## Mesures

### Échantillon de l'archive (92 messages, étiquettes proposées, à vérifier par Nicolas)

| | Ancien Rocky | E2 (règles `mail-classify-2026-10-05.5`) |
|---|---|---|
| Catégorie juste | 37 / 92 (40 %) | 80 / 81 décidés par les règles (99 %) |
| Rattachements faits | 50, dont **31 faux** | 13 de confiance moyenne, **0 faux** ; 7 « À vérifier », dont 3 justes |
| Laissés au modèle | — | 11 (12 %) |
| Cas imposés | Quora → French bee, METRO → Ministère, OVH / Google Agenda → Choisir le Service Public… | aucun rattachement (`test_classification_archive.py`) |

### Boîte de Nicolas (base de développement, 517 messages relevés depuis la recette d’E1)

| Passage | Résultat |
|---|---|
| Règles seules (`--sans-llm`) | 504 décisions (97,5 %), 13 messages laissés au modèle |
| Modèle (Gemini, `--limite`) | 13 appels, 13 décisions, 0 réponse refusée ; durée moyenne 1 s |
| Appels au total pendant l'étape | **42** (plafond fixé par Nicolas : 200) : 29 au premier passage (9 refusés, cause trouvée : corps à entités HTML), 13 au dernier |
| Répartition (en vigueur, `.6`) | Hors recherche 254 (57 sûrs), alertes 170, accusés 62, refus 15, avis de plateforme 15, approche de recruteur 1 |
| Vue par défaut (Q19) | 92 messages avant l'affinage, **23** après : 15 refus, 7 « Finalisez votre candidature… », 1 approche ; 62 accusés comptés hors de la vue |

Erreurs relevées et corrigées en cours de mesure (versions `.2` à `.5`) : questionnaire Hellowork lu comme un refus, refus
conditionnels, newsletter « case study » classée en test, alertes eFinancialCareers et Hellowork non reconnues, avis de
sécurité Google envoyés au modèle, corps à entités HTML, fil des avis de plateforme, refus « Nous n'irons pas plus loin »
(Team.is). Erreur restante connue : une newsletter (Order and Chaos) classée « alerte emploi » par le modèle.

### Vérification et essai

| Contrôle | Résultat |
|---|---|
| Critère, par les tests | Contraintes de preuve refusées par la base (`test_the_base_refuses_a_decision_without_proof`) ; chaque décision écrite a règle, extrait, raisons et événement ; Quora jamais rattaché à French bee (règles, archive, PostgreSQL) |
| Vérification globale | `docker compose run --rm --build check` : **1 340 tests en 1 min 10** |
| Migration `0014` (base de développement) | `upgrade` → `downgrade -1` → `upgrade head` |
| Essai dans Chromium (instance à part, schéma jetable, compte et messages fictifs, modèle simulé) | Vue « À regarder » : refus French bee et accusé Covéa liés à leur dossier, message du modèle, message en attente avec sa raison ; « Alertes » : l'alerte LinkedIn seule ; « Pourquoi ? » lisible ; domaine « rh@frenchbee.com » enregistré « frenchbee.com » dans le dossier. Console sans erreur. Corrigé : libellé « Modèle de langage » en double, colonne du classement trop étroite |


## Recette (Nicolas, 05/10)

| Point | Résultat |
|---|---|
| Premier essai | Tri à affiner, « À vérifier » sans geste : affinage Q19–Q22 (vue par défaut de 92 à 23 messages), corrections reportées en E4, avancée avant E3 |
| Étiquettes de l'échantillon | Proposées par l'agent, acceptées par Nicolas à la clôture sans relecture ligne à ligne (colonne `checked` vide) : à reprendre avec les corrections d'E4, qui donneront des étiquettes de Nicolas |
| Appels Gemini pendant l'étape | 42 (plafond fixé : 200) |

**Étape close** (Nicolas, 05/10) : critère vérifié par les tests (preuve exigée par le schéma, Quora jamais rattaché à
« French bee », jeu issu de l'archive) et sur sa boîte de développement ; vérification globale verte.

## Hors E2

Transitions des candidatures, corrections et règles par compte (E4) ; offres tirées des alertes (E3) ; InMail de
recruteurs arrivées par les notifications LinkedIn (E4).
