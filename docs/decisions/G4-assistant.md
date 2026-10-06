# G4 — Assistant Rocky

Date : 07/10/2026 · Étape : G4 (plan v2) · Préparation : *grill me* (Q1–Q33), puis mode plan

Le tiroir 🐾 devient un assistant branché sur les données du compte (révise la décision F1, Q2 ; décision de Nicolas
du 05/10). Au grill, l'étape s'est élargie : changement de fournisseur de modèle par le port `JsonModel` et mesure des
coûts de **tous** les appels au modèle, pour fixer le plafond de la bêta d'après la semaine de recette.

Critère de sortie (fixé au grill, Q15 et Q26) :

1. sur les vraies données de Nicolas, des **questions de référence** reçoivent une réponse qui cite ses faits :
   2 sur une offre, 2 sur une candidature, 1 sur un message, 2 sur le cockpit (liste en fin de document) ;
2. la 6ᵉ question du jour reçoit le message du plafond ; une panne du modèle, un message clair ;
3. aucune écriture hors des tables de l'assistant et des appels au modèle (test) ;
4. les coûts sont visibles dans ⚙️ Système, globaux et par type d'appel, et par `rocky-admin couts` ;
5. recette de Nicolas ; vérification globale verte en local et sur GitHub ;
6. les questions de référence sont posées à **au moins deux fournisseurs** (clés et accord de Nicolas) ; réponses et
   coûts comparés ici.

## Constats de départ

| Constat | Source |
|---|---|
| Le tiroir est **par écran** : `GET /tiroir?ecran=<clé>` lit un registre `add_drawer` ; il ignore l'offre, le dossier ou le message affiché. Il est rechargé à chaque ouverture (`toggle`) et se ferme au moindre clic à côté (`popover` automatique) | `rocky/system/shell.py` (`Drawer`, `add_drawer`, `/tiroir`), `templates/layout.html` ; décision F1 (Q12, Q13) |
| « À faire ici » répète, sur le cockpit, les gestes du héros | Plan §8 (G3 → G4) |
| Un seul adaptateur de modèle, `GeminiModel` : un tour, sortie JSON contrainte, 30 s, aucun réessai ; il ne rend pas les jetons consommés. Il est posé sur `app.state.llm_model` par `offres/imports/web.py` | `rocky/system/llm.py`, décision C3 |
| Seul le classement des messages (E2) est plafonné : par compte, 1 h et 24 h glissantes, table `mail_model_calls` (dont `message_id` est obligatoire). Résumé d'offre, import du CV, traduction, lettre, message au recruteur : aucune mesure | `rocky/messages/classification/usecases.py` (`_stop_reason`), `rocky/messages/sql.py` |
| Les modules donnent des lectures publiques (`offres/api.py`, `candidatures/api.py`, `profil/api.py`) ; les messages passent par `MessagesService` | Étape H4 |
| Aucune table ni aucun événement de conversation | — |

## Décisions métier (grill avec Nicolas, 07/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Rôle | L'assistant **explique** (« pourquoi ce score ? »), **retrouve** (« où en est ma candidature ? ») et **conseille** (« par quoi je commence ? »). Il ne **rédige** pas : la rédaction viendra avec le suivi et les relances, dans un plan après F2 (§8). |
| Q2 | Contexte | L'**objet affiché** (offre, candidature, message) et un **résumé compact du compte** ; sans objet affiché, le résumé seul. |
| Q3 | Conversations | Enregistrées en base, par compte, sous une forme structurée (historique, mémoire par objet). Gardées entières pour l'instant (données d'entraînement) ; pour un déploiement plus large, un résumé avant stockage (§8). |
| Q4 | Faits | Le serveur assemble un **dossier de faits figé** mis dans le prompt : un appel par question, jamais de SQL écrit par le modèle. |
| Q5 | Citations | Sortie structurée `{reponse, faits, sans_reponse}` ; chaque fait du dossier porte un identifiant, vérifié par le serveur ; les faits cités s'affichent sous la réponse, avec un lien vers leur écran. Règles très resserrées au départ, assouplies à l'usage. |
| Q6 | « À faire ici » | **Supprimé partout** : le tiroir était là en attendant l'assistant. Les raccourcis restent derrière « ? ». |
| Q7 | Indisponible | Un message simple et clair : « Assistant indisponible : plafond du jour atteint, il revient demain » (ou la raison de la panne) ; aucun repli sur des gestes. |
| Q8 | Plafond | **5 questions par jour de Paris et par compte**, réglable (`ROCKY_ASSISTANT_DAY_LIMIT`) ; le restant est affiché ; une question que le modèle n'a pas pu traiter n'est pas décomptée. Le plafond de la bêta (10 utilisateurs) sera fixé d'après les coûts de la semaine de recette. |
| Q9 | Appels communs | Une table **`model_calls`** dans `system` ; seul l'assistant y est plafonné ; les autres appels y sont inscrits sans plafond, pour mesurer les coûts. Le plafond du classement des messages reste sur sa table : sa migration se fera à part, proprement (§8). |
| Q10 | Mémoire | Par objet : rouvrir le même objet un autre jour reprend la conversation ; les **6 derniers tours** sont envoyés au modèle. Une mémoire de compte résumée, réinjectée partout : §8. |
| Q11 | Dossier de faits | **Offre** : titre, entreprise, lieu, contrat, date limite, score et détail par composante (preuves, manques), pistes, décision en vigueur et raison, résumé de l'annonce s'il existe (jamais généré pour l'occasion), description coupée. **Candidature** : étape, dates, prochaine action, lettre ou non, documents (noms), messages liés (classement, extrait justificatif). **Message** : expéditeur, objet, date, classement, extrait justificatif, candidature liée ; **jamais le corps**. **Résumé du compte** : pistes, compétences principales, chiffres du cockpit, relances dues. Budget d'environ 12 000 caractères, la description coupée d'abord. |
| Q12 | Réponse non étayée | Aucune citation, identifiant inconnu ou forme invalide : la réponse est **remplacée** par « Je ne trouve pas de quoi répondre dans tes données », la réponse brute gardée en base (issue « rejetée »). Une réponse « je ne sais pas » prévue par le schéma (`sans_reponse`) s'affiche telle quelle. Les consignes interdisent au modèle d'affirmer avoir fait un geste. |
| Q13 | Suggestions | 2 ou 3 questions toutes prêtes, fixes, fournies par le module de l'objet ; chacune coûte une question. |
| Q14 | Modèle de l'assistant | Réglable à part, avec repli sur le modèle commun ; le **changement de fournisseur** passe par le port `JsonModel` dès G4, pour essayer d'autres fournisseurs sans retoucher le code. |
| Q15 | Critère de sortie | Les points 1 à 5 ci-dessus. |
| Q16 | Coûts | Jetons (le fait mesuré) et **≈ €** (une estimation, avec la date du tarif) par un tableau de tarifs versionné ; un modèle absent du tableau affiche « tarif inconnu », jamais 0 €. |
| Q17 | Classement des messages | Il inscrit aussi chacun de ses appels dans la table commune ; son plafond ne change pas. |
| Q18 | Types d'appels | Assistant, Résumé d'offre, Import du CV, Traduction, Lettre, Message au recruteur, Classement des messages, puis le total ; aujourd'hui, 7 jours, 30 jours ; les échecs comptés à part. |
| Q19 | Portée des coûts | ⚙️ Système montre le compte connecté ; `rocky-admin couts` tous les comptes, par compte et par type. Une vue d'administrateur dans l'interface : §8, avant la bêta. |
| Q20 | Sans objet affiché | Une **conversation générale** du compte, qui reprend comme les autres ; « Nouvelle conversation » partout (l'ancienne reste en base, plus envoyée au modèle). |
| Q21 | Ton et langue | La langue de la question, le français par défaut ; tutoiement, phrases courtes (G3, Q23) ; les faits par leur nom, jamais par un identifiant interne. |
| Q22 | Effacement | Pas en G4 (un seul utilisateur) ; effacement par compte et durée de conservation : §8, avant la bêta. |
| Q23 | Fournisseurs | **Gemini, Anthropic, OpenAI, Mistral** (hébergé en Europe : un argument pour la bêta), sans SDK. Un modèle local : §8. |
| Q24, Q28 | Configuration | Fournisseur et modèle en **deux variables** : `ROCKY_MODEL_PROVIDER` et `ROCKY_MODEL_NAME` par défaut, surcharge par type `ROCKY_<TYPE>_MODEL_PROVIDER` et `ROCKY_<TYPE>_MODEL_NAME` (les deux ensemble, sinon l'application refuse de démarrer, avec un message clair) ; une clé par fournisseur `ROCKY_<FOURNISSEUR>_API_KEY`. L'ancien `ROCKY_GEMINI_MODEL` reste lu, avec un avertissement, tant que `ROCKY_MODEL_NAME` manque. Une clé absente ne bloque pas le démarrage : les appels du type concerné sont « indisponibles », avec la raison. |
| Q25 | Granularité | Le modèle se règle **par type d'appel** (types de Q18) ; chaque appel garde son fournisseur et son modèle. |
| Q26 | Critère 6 | Les questions de référence posées à au moins deux fournisseurs pendant la recette, comparées ici. |
| Q27 | Saisie | Le tiroir ne se ferme que par « Fermer » ou Échap ; la question en cours est gardée en le refermant ; « Envoyer » est désactivé et « Rocky réfléchit… » affiché pendant l'appel. |
| Q29 | Journal | Aucun événement pour une question : le journal reste aux décisions et transitions (cockpit, séries, Bilan ; une question n'est pas un jour actif). |
| Q30 | Découpage | Une seule étape, deux blocs de commits (socle des modèles, puis assistant) ; poussée sur `origin` après le premier. |
| Q31 | Message affiché | Sur 📬 Messages, le message dont le panneau « Corriger » est ouvert ; sinon la conversation générale. |
| Q32 | Suggestions générales | « Par quoi je commence aujourd'hui ? » et « Où en est ma recherche cette semaine ? ». |
| Q33 | Tarifs | Relevés par l'agent sur les pages officielles des fournisseurs (sources et taux de change datés), vérifiés par Nicolas avant la recette. |

## Décisions techniques

### Bloc 1 — socle des modèles

| Sujet | Décision | Raison |
|---|---|---|
| Port | `rocky/system/llm/` devient un paquet : `port.py` (`JsonModel`, `LlmUnavailableError`, `Usage`, `Completion`, `HttpAdapter` : clé, requête, raisons d'un refus), un module par fournisseur ; les imports `rocky.system.llm` restent valables | Q23 : un adaptateur par fournisseur derrière le même port, sans SDK (aucune dépendance ajoutée) |
| Anthropic | `POST /v1/messages`, `output_config.format` (`json_schema`) ; ni température ni outil forcé (refusés par les modèles actuels) ; `max_tokens` 16 000 ; schéma adapté (`additionalProperties: false` sur chaque objet, bornes retirées) | Sorties structurées de l'API ; l'appelant vérifie toujours la forme |
| OpenAI, Mistral | `chat/completions`, `response_format` `json_schema` en mode non strict ; température 0,2 pour Mistral seulement (les modèles de raisonnement d'OpenAI la refusent) | Les schémas de Rocky ne sont pas tous écrits pour le mode strict |
| Jetons | Gemini : `promptTokenCount`, sortie = `candidatesTokenCount + thoughtsTokenCount` (la réflexion est facturée) ; Anthropic : entrée + jetons du cache ; OpenAI, Mistral : `prompt_tokens`, `completion_tokens` ; absents → inconnus | Q16 |
| Configuration | `LlmSettings(default, overrides, keys, …)`, `CallType`, `Provider` dans `config.py` ; une paire incomplète, un fournisseur inconnu, un fournisseur sans nom de modèle arrêtent le démarrage ; `ROCKY_GEMINI_MODEL` lu en repli avec un avertissement | Q24, Q28 |
| Inscription | Table `model_calls` (migration `0020`) ; `Models` sur `app.state.models` (posé par `create_app`) ; `model_for(request, type, account)` rend un `RecordedModel` qui inscrit chaque appel dans **sa propre** courte transaction ; sans clé, rien n'est envoyé ni écrit | Q9 ; un appel n'est jamais dans la transaction métier de la route |
| Classement des messages | `MessagesService(record=…)` : le modèle de chaque compte est enveloppé à l'inscription (`model_of`) ; ses plafonds restent sur `mail_model_calls` | Q17 ; la migration des plafonds E2 se fera à part (§8) |
| Tarifs | `prices.py` : dollars par million de jetons (pages officielles relevées le 07/10/2026 ; Mistral Medium et Small lus sur une source tierce, **à vérifier**), cours BCE du 06/10/2026 (1 € = 1,1269 $) | Q16, Q33 |
| Coûts | `costs.py` : regroupement par compte, type et modèle depuis le minuit de Paris de chaque période ; un appel sans tarif ou sans jetons est compté « sans tarif » ; panneau « 🧮 Appels au modèle » en dernier dans ⚙️ Système (sans geste) ; `rocky-admin couts` | Q18, Q19 |
| Tests | `tests/system/llm/` (adaptateurs sur `MockTransport`, inscription, coûts) ; `use_model(app, faux)` remplace `app.state.llm_model` dans les tests web | AGENTS §7 |

### Bloc 2 — l'assistant

| Sujet | Décision | Raison |
|---|---|---|
| Place | `rocky/system/assistant/` : `model.py` (pur : `Fact`, `FactSheet`, `Subject`, budget `fit`, consignes, `prompt`, `checked`), `registry.py`, `sql.py`, `usecases.py`, `web.py` | D13 : pas de cinquième module ; `system` n'importe aucun module métier |
| Faits | Registres `add_facts(app, type, lecteur)` (plusieurs lecteurs par type : `messages` ajoute les messages d'un dossier) et `add_summary(app, clé, lecteur)` (`profil`, `cockpit`, `candidatures`) ; branchés par la composition (`system/web.py`) ; chaque module a son `assistant.py` | Q2, Q4, Q11 ; même forme que les parties du cockpit (lecteurs sur la requête et le compte) |
| Fiche d'une offre | Construite comme l'écran (`offer_card`) sur les seules lectures de l'offre (jamais la liste) ; composantes du score avec leur valeur, leur poids, leur détail et leurs preuves | Règle de l'écran Offres : une route qui vise une offre ne lit pas la liste |
| Fiche d'un dossier | Lecture **sans verrou** (`SqlApplicationStore.application`), étape et prochaine action calculées, envoi, documents, notes, chronologie du dossier (`timeline`, 20 dernières lignes) | Q11 ; un lecteur ne verrouille rien |
| Résumé du compte | Pistes, compétences (clés d'abord), objectif ; candidatures ouvertes (relances en retard d'abord) ; ce que montre le cockpit (problèmes, priorité, instruments, état, progression, fil de 7 jours) | Q11 |
| Identifiants | `<type>.<champ>` : `offre.score.skills`, `candidature.etape`, `message.justification`, `compte.candidature_12`, `cockpit.offres` ; jamais `candidatures.…` (réservé aux événements, test de la chronologie) | Q5 |
| Lecture seule | Garantie par un test qui écoute toutes les requêtes SQL d'une suite de questions : seules `model_calls`, `assistant_conversations`, `assistant_turns` (et la session renouvelée par l'authentification) sont écrites ; aucun `FOR UPDATE` | Critère 3 ; la transaction `READ ONLY` prévue au plan ne convenait pas aux lecteurs du cockpit, qui ouvrent leurs connexions |
| Conversations | Migration `0021` : `assistant_conversations` (sujet nul = générale ; la plus récente est en cours) et `assistant_turns` (question, réponse montrée, faits cités, réponse brute, issue, appel) ; ajout seul tenu par le code, pour permettre l'effacement RGPD (§8) | Q3, Q10, Q20, Q22 |
| Question | `ask` : question vide ou trop longue (1 000 caractères), modèle sans clé, plafond (jour de Paris, appels `ok` et `rejected`) ; faits lus seulement si la question part ; appel hors transaction ; appel et tour écrits ensemble | Q8, Q12 |
| Tiroir | `popover="manual"` ; ouverture : `GET /tiroir` avec le formulaire `#rocky-question` (le champ caché `objet` y est rattaché) ; suggestions et « Nouvelle conversation » portent leur sujet ; champ vidé par un échange hors bande après une réponse, gardé sinon ; « Envoyer » et suggestions désactivés pendant l'appel ; Échap : `rocky.js` cherche d'abord dans un tiroir ouvert (les raccourcis de l'écran ne bougent pas derrière lui) | Q27 ; vu à l'essai : un `hx-include` sans correspondance écrit une erreur en console |
| Retrait | « À faire ici », `Drawer`, `add_drawer`, les six `_drawer` des modules, `due_actions` et leurs tests | Q6 |

## Essai (07/10)

Instance à part : schéma jetable de `test-db`, compte fictif (une offre « Data analyst », son dossier préparé), faux
modèle qui cite les deux premiers faits reçus ; Chromium sans fenêtre (Playwright), 1 280 px puis 390 px.

| Contrôle | Résultat |
|---|---|
| Cockpit | « À propos de : Conversation générale », deux suggestions, « Il te reste 5 questions aujourd'hui » ; une suggestion → réponse, « D'après : Piste de recherche · … » en liens, « Il te reste 4 » |
| Saisie | Échap quitte le champ puis ferme le tiroir ; la question tapée est gardée à la réouverture ; un clic à côté ne ferme pas ; après une réponse, le champ est vidé |
| Fiche d'une offre | « À propos de : Data analyst (H/F) chez Exemple », les trois suggestions de l'offre ; réponse citant « Intitulé · Entreprise » |
| Règles resserrées | Réponse citant un fait inconnu → « Je ne trouve pas de quoi répondre dans tes données. » ; `sans_reponse` → « Tes données ne le disent pas. » |
| Plafond | La 6ᵉ question : « Assistant indisponible : plafond du jour atteint, il revient demain. », la question tapée gardée |
| Dossier, téléphone | « À propos de » le dossier ; tiroir plein écran à 390 px, ouvert par « Plus » → « Rocky » |
| Console | Sans erreur ni avertissement (après correction) |

Corrigé pendant l'essai : le message du plafond affiché deux fois ; l'erreur de console de `hx-include` sur les pages
sans objet.

Vérification globale (`docker compose run --rm --build check`) : **1 819 tests**, verte, 77,5 s de pytest et 1 min 22
au total en local ; un premier passage du bloc 1, la machine très chargée (charge 97), avait pris 2 min 00. Sur GitHub :
verte, pytest en 100 s (bloc 1) puis 118 s (bloc 2), contre 74 s à la fin de G3 (noté au plan, §8).

## Questions de référence

À poser sur les vraies données de Nicolas (critère 1), à au moins deux fournisseurs (critère 6). Le plafond de 5
questions par jour se relève pour la recette (`ROCKY_ASSISTANT_DAY_LIMIT`).

| Objet | Question |
|---|---|
| Une offre (sa fiche ou le tri) | « Pourquoi ce score ? » ; « Qu'est-ce qui me manque pour ce poste ? » |
| Un dossier | « Où j'en suis ? » ; « Quand relancer ? » |
| Un message (panneau « Corriger ») | « Qu'est-ce que ce message change pour moi ? » |
| Le cockpit | « Par quoi je commence aujourd'hui ? » ; « Où en est ma recherche cette semaine ? » |

## Recette

*(à venir)*
