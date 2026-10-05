# D3 — Ciblage et traduction

Date : 30/09/2026 · Étape : D3 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q24) puis mode plan

Critère de sortie (plan) : « CV anglais ciblé sans ressaisie », précisé par Q15 ci-dessous.

## Constats de départ

| Constat | Source |
|---|---|
| Le CV se construit depuis le seul CV maître (`CvLayout`) : aucune sélection par offre | `rocky/profil/cv/content.py` (`cv_content`) |
| Un gabarit déduit (format `rocky-cv-gabarit/3`) ne remplit que groupes, transversales et projets ; le reste est l'image du CV français importé. Le PDF importé n'est pas gardé (D2, Q14), seule la réponse du modèle l'est | `rocky/profil/cv/derived.py`, `importer.py` |
| La stack d'un projet n'a pas d'anglais ; un CV anglais la montre en français sans le signaler | `content.py`, migration `0003` ; constat D2 → D3 |
| L'analyse d'annonce (C3) rattache ses compétences par **libellé français**, avec leur importance ; elle n'est ni stockée ni exposée aux autres modules | `rocky/offres/analysis/rules.py`, `offres/web.py` |
| Un dossier (`applications`) n'a pas de page ; il vit dans l'encart de la fiche d'offre et la liste brute | `rocky/candidatures/web.py` |
| Aucun code de traduction ni glossaire dans le nouveau Rocky. L'ancien traduisait le texte du PDF ligne à ligne, sans glossaire, dans une page sans design | `dashboard/rocky/profile_documents.py` (historique) |
| Nicolas n'a pas de CV anglais Canva : sans CV anglais importé, le gabarit neutre déborde de 77 mm avec son parcours | décision D2, clôture |

## Décisions métier (grill avec Nicolas, 30/09)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Où naît le CV ciblé | Depuis le **dossier de candidature**. Aperçu recalculé à la demande, jamais stocké : les révisions immuables sont D5. |
| Q2 | Ce qui varie | La **sélection et l'ordre** des trois blocs variables (groupes de compétences techniques, transversales, projets). Aucune réécriture de texte. |
| Q3 | Qui choisit | Des **règles déterministes** proposent, l'utilisateur ajuste (ajouter, retirer, réordonner) ; chaque élément a sa raison derrière « Pourquoi ? ». Aucun LLM. |
| Q4 | Ajustement | Gardé **dans le dossier** (sélection propre à la candidature, figée par D5), journalisé : donnée d'entraînement (D14). |
| Q5 | Traduction | Le LLM traduit les champs du profil sans anglais ; chaque champ validé est **enregistré dans le profil** et resservi à tous les CV. Le rendu anglais refuse toujours tant qu'un champ affiché manque (D2, Q11), avec le geste « Traduire les champs manquants ». |
| Q6 | Glossaire | Les libellés anglais des compétences, plus des paires FR → EN **propres au compte** (à imposer, ou à ne pas traduire). Passés au modèle comme contraintes et **vérifiés après sa réponse** : un terme du glossaire présent en français doit se retrouver tel quel en anglais, sinon la proposition est signalée. Édition dans Profil & kit ; ajout en un geste depuis la relecture. |
| Q7 | CV anglais de Nicolas | Pas de CV anglais Canva : Rocky produit l'anglais **à partir du français**. |
| Q8 | Design du CV anglais | Le **design du CV importé**, en version anglaise dérivée du même import : calque sans texte, toutes les rubriques en zones remplies en anglais ; un débordement reste une erreur visible (D2, Q6). |
| Q9 | Langue | Deux boutons **CV français / CV anglais** sur la même sélection ; aucune détection de la langue de l'annonce. |
| Q10 | Règles de ciblage | Point de départ : le CV maître. Dans chaque groupe, les compétences citées par l'annonce remontent en tête (éliminatoire, puis un plus, puis mentionnée, puis l'ordre du CV maître) ; une compétence citée, hors du CV maître mais rangée dans un groupe, est **ajoutée**. L'ordre des groupes ne change pas (design). Même règle pour les transversales. Projets : tous ceux du profil classés par les compétences de l'annonce qu'ils prouvent, pondérées par l'importance ; les meilleurs remplissent les emplacements du gabarit ; à égalité, l'ordre du CV maître. **Rien n'est retiré en silence** : un débordement nomme le bloc, l'utilisateur retire. |
| Q10 bis | Compétence technique citée hors du CV maître | Une compétence technique n'a de groupe que dans le CV maître (`ck_skills_cv_placement`) : citée par l'annonce mais hors du CV maître, elle est **proposée, pas ajoutée** (« ➕ dans ton profil, pas dans le CV », geste « Ajouter dans le groupe … »). Les transversales citées, sans groupe, sont ajoutées tant que le gabarit a de la place ; au-delà, proposées de même. |
| Q11 | Couverture de l'annonce | Dans le dossier, chaque compétence éliminatoire ou « un plus » de l'annonce : ✅ dans le CV, ➕ dans le profil mais pas dans le CV, ❌ absente du profil. Déterministe, sans score composite (reprend D2, Q12). |
| Q12 | Champs traduits | Nom, problème, travail, résultats des projets ; **stack** des projets (nouvelle version anglaise) ; libellés des compétences, noms des groupes, loisirs. Employeurs, lieux, noms propres ne sont jamais traduits. |
| Q13 | Validation | Traduction **sur geste** seulement (Profil & kit, et le dossier quand le CV anglais refuse) ; un appel au modèle, précédé d'une mention de ce qui est envoyé ; relecture champ par champ (français, anglais proposé : accepter, modifier, ignorer) ; chaque champ accepté est écrit dans sa propre transaction avec l'événement `profil.translation_accepted`. Rien de non validé n'est stocké. |
| Q14 | Français modifié ensuite | L'empreinte du français d'origine est gardée avec la traduction : si le français change, l'anglais est marqué **« à revoir »** et le rendu anglais l'**avertit**, sans refuser. Un anglais saisi à la main n'est jamais marqué. |
| Q15 | Critère de sortie | Sur 2 à 3 annonces réelles de pistes différentes : dossier préparé, ciblage appliqué, champs manquants traduits (vrais appels Gemini, avec l'accord de Nicolas), validation **sans écrire de phrase anglaise** (corriger un mot est permis) ; CV anglais sans débordement, « Vérifier mon CV » vert ; validation visuelle de Nicolas. |
| Q16 | Rubriques non variables en anglais | **Traduction du texte du CV français importé**, rubrique par rubrique, validée, gardée avec le gabarit anglais. Rien n'est généré : âge et accroche sont traduits tels quels (cohérent avec D2, Q29, Q30). |
| Q17 | Deux gabarits anglais | Le **dernier créé** est actif (import d'un CV anglais ou traduction), l'autre reste réactivable (règle de D2, Q24). |
| Q18 | Création du CV anglais | Geste « Préparer mon CV anglais » dans Profil & kit, quand un gabarit français déduit est actif : un appel traduit les rubriques gardées et les champs manquants des blocs variables ; relecture rubrique par rubrique avec **aperçu** du CV anglais ; le gabarit anglais n'est créé que quand **toutes** les rubriques sont validées (dossier immuable, empreinte du gabarit français d'origine, événement `profil.cv_template_derived`, langue `en`). |
| Q19 | Réimport du CV français | **Mémoire de traduction** par compte (phrase française → anglais validé) : au prochain « Préparer mon CV anglais », les lignes inchangées sont reprises sans appel, seules les nouvelles partent au modèle. Un CV anglais issu d'un ancien gabarit français est rendu avec un avertissement. |
| Q20 | Placement de l'anglais | Éléments d'une ligne (dates, intitulés, écoles, langues, titre) : position et style gardés. Paragraphes et puces sur plusieurs lignes : recalculés dans la zone de leur rubrique. Gras conservé (`**…**`). Trop long : erreur visible qui nomme la rubrique, vue dans l'aperçu **avant** de valider ; aucune réduction. |
| Q21 | Protections | **Jamais envoyés** au modèle, recopiés : nom, e-mail, téléphone, adresses, liens. **Jamais traduits** : employeurs, écoles, lieux, noms de projet déjà en anglais. Le glossaire explicite l'emporte. |
| Q22 | Périmètre | Les limites notées à la clôture de D2 (blocs projets approximatifs, un seul design, gabarit neutre court) ne sont pas reprises, sauf si l'une bloque le critère. Hors D3 : lettre (D4), révisions et envoi (D5), écran Candidatures complet (D6), adaptation des expériences (bêtas). |
| Q23 | Écran | Nouvelle **page du dossier** `/candidatures/<dossier>`, avec pour l'instant la seule étape « CV » ; on y arrive depuis la liste et l'encart de la fiche d'offre. D6 y ajoutera lettre, envoi et suivi. **Élargie par Q25 (recette, 04/10).** |
| Q25 | Parcours du dossier (recette, 04/10, plan de conception inspiré du dossier en 3 cartes de V1) | La page du dossier montre un **fil 1. CV → 2. Lettre → 3. Envoi**, calculé de l'étape du dossier. « Préparer la candidature » **atterrit sur le dossier**. « **CV prêt : passer à l'envoi** » passe à « Prête à envoyer » (tant que la lettre n'existe pas, « prête » = CV prêt ; D4 tranchera). L'étape Envoi propose les CV, « **Ouvrir le site de candidature ↗** » (`application_url`, à défaut l'annonce, domaine affiché) et « **J'ai envoyé ma candidature** » (étape « Envoyée », relance à J+7), sans case à cocher : tout se défait par « Annuler ». Rocky ne remplit ni n'envoie rien. L'étape Lettre dit « à venir ». Gestes par les cas d'usage existants (journal). Objectif : « Prête à envoyer » en 2 clics depuis une offre « Intéressé ». |
| Q26 | Offres retenues sans dossier | La page 📝 Candidatures montre aussi « **À préparer** » : les offres dont la dernière décision est « Intéressé » et qui n'ont pas de dossier ouvert, avec « Préparer la candidature » qui mène au dossier. Le raccourci depuis le mode tri reste pour D6. |
| Q24 | Source du CV anglais | Le gabarit passe au **format 4** : il garde aussi le calque sans texte et les rubriques gardées mesurées ; le PDF n'est toujours pas conservé (D2, Q14). Nicolas réimporte son Canva français une fois ; la réponse du modèle déjà conservée est réutilisée si le texte du PDF est identique. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Accès à l'analyse | `offres/web.py` expose `offer_analysis` (fonction publique, sur la connexion de l'appelant) | `candidatures` ne lit pas les tables d'`offres` (AGENTS §4). |
| Règles de ciblage | Fonctions pures dans `rocky/candidatures/targeting.py` : `CvLayout` ciblé, raisons, couverture ; les gestes réutilisent `rocky/profil/cv/layout.py` | Testables sans base ; un seul format de sélection pour le CV maître et le CV ciblé. |
| Sélection du dossier | Ajout seul : une ligne par ajustement (la dernière est en vigueur ; « Revenir à la proposition » ajoute une ligne vide), avec son événement `candidatures.cv_selection_changed` | Règle du module : un dossier est une suite de changements, jamais réécrits. |
| Traduction | Règles pures et cas d'usage dans `rocky/profil/translation.py` ; un appel `JsonModel.complete_json` ; contrôles après réponse (identifiants, gras, glossaire, protégés) | Le LLM ne décide jamais seul ; toute proposition est vérifiée puis validée par l'utilisateur. |
| « À revoir » (Q14) | Déduit de la mémoire de traduction : un anglais validé pour un autre texte français est à revoir ; aucune table d'état par champ | Un seul endroit (la mémoire) ; un anglais saisi à la main n'y est pas, il n'est jamais marqué. |
| Sélection sur un CV maître modifié | La sélection gardée nomme ses groupes ; si les groupes du CV maître ont changé, elle ne se place plus : les règles proposent à nouveau et l'écran le dit | Les groupes sont réécrits à chaque enregistrement du CV maître (pas d'identifiant stable) ; rien n'est deviné en silence. |
| Champs traduisibles | Tous les textes qu'un CV peut montrer : blocs variables, et ce que montre aussi le gabarit neutre (titre, accroche, intitulés et puces des expériences) | « Traduire les champs manquants » répond à tout refus du CV anglais, gabarit déduit ou neutre. |
| Format 4 du gabarit | À l'import, le gabarit garde aussi `calque-sans-texte.png` (la page sans aucun texte) et ses **unités** : une ligne seule, un paragraphe (lignes renvoyées à la ligne, jointes) ou un titre de section, avec style, gras (`**…**`) et italique (`_…_`) marqués. Un gabarit du format 3 reste rendu en français ; sa version anglaise demande un réimport | Aucun PDF gardé ; rien de redessiné. |
| Version anglaise | Gabarit à part (langue `en`, `source_sha256` du gabarit français) : calque sans texte, chaque unité écrite dans son anglais validé ; une ligne garde sa place et peut s'étendre jusqu'au texte voisin à sa droite ; un paragraphe s'écoule dans sa boîte, plus une ligne d'air ; les étiquettes des cartes projets (« Problématique ») se traduisent une fois. Nom, e-mail, téléphone, ville, liens : recopiés, jamais envoyés | Q20, Q21 ; même mesure du débordement qu'en D2. |
| Titres anglais | Dessinés en tracés (`fonttools`, MIT, réintroduit par `uv add`) avec l'espacement mesuré, et leurs mots en texte invisible pour les lecteurs de PDF | Décision D2 « Titres des sections » : un titre espacé en texte se lit lettre par lettre. |
| Réimport identique (Q24) | L'import garde l'empreinte du texte envoyé (`texte-lu.sha256`) ; un nouvel import du même texte reprend la réponse gardée (`FileStore.find_bundle`, dossier relu et vérifié) | Aucun appel inutile ; aucun fichier modifiable hors des dossiers immuables. |
| Découpage en unités (recette, 03/10) | Une ligne prolonge le paragraphe du dessus si elle garde son **retrait** et que la ligne du dessus est remplie **ou** trop pleine pour son premier mot ; une ligne qui ouvre en gras comme la première, après une fin de phrase ou une autre ligne ouvrant en gras, commence un **nouvel élément** (langues, puces). Deux lignes de titre empilées de même colonne forment **un seul titre**, traduit d'un bloc puis réparti sur les lignes françaises (`title_lines`) | Sur le Canva de Nicolas : les trois langues étaient un seul paragraphe (« French (Native) English… »), deux puces étaient réunies (puce dessinée devant le mauvais mot), « COMPÉTENCES / TECHNIQUES » donnait « SKILLS / TECHNICAL ». Un réimport refait le gabarit (réponse du modèle reprise). |
| Corriger un texte validé (recette, 03/10) | Geste « Modifier » sur chaque texte validé de l'écran CV anglais, ouvert d'office quand l'aperçu déborde ; la correction remplace l'entrée de la mémoire | Le message de débordement demande de raccourcir un texte (Q20) : sans ce geste, rien ne le permettait. |
| Aperçus (recette, 03/10) | Aperçus de l'import et du CV anglais à 150 dpi (70 et 80 avant) ; les liens de téléchargement de Profil & kit ne sont plus « boostés » par HTMX | Aperçus flous sur écran haute densité ; un téléchargement boosté collait le PDF dans la page et figeait l'onglet. |
| Place d'un texte anglais (recette, 04/10) | Une ligne s'étend jusqu'au texte voisin à sa droite, **sans dépasser le bord droit le plus lointain des textes de sa colonne** (un trait dessiné peut se tenir au-delà) ; un paragraphe s'arrête **au texte qui le suit en dessous** (plus de ligne de marge qui le recouvre). Au-delà : débordement visible, nommé | Sur le CV de Nicolas, « Project management… » passait à 3 lignes et recouvrait la puce suivante, « B2 » était coupé par le trait bleu : aucun n'était signalé. |
| Vérifier le CV d'une candidature (recette, 04/10) | « Vérifier ce CV / Check this CV » dans l'étape CV du dossier : mêmes trois lecteurs que « Vérifier mon CV », sur le CV ciblé (sélection du dossier, langue choisie) ; affichage commun (`profil/cv_check.html`). Un vrai ATS pourra s'y brancher plus tard | Le CV envoyé est le CV ciblé, pas le CV maître (Q15). |
| Gabarits dans Profil & kit (recette, 04/10) | Seul le gabarit en service reste visible ; les autres sont repliés sous « Autres gabarits », avec leur date de création | Quinze boutons « Utiliser » indiscernables. La suppression d'un gabarit reste à faire (section 8). |
| Tests | Un seul import du CV fictif pour toute l'exécution (`tests/profil/cv/conftest.py`, portée session) : chaque dérivation dessine deux calques à 300 dpi | Vérification globale sous 2 min (68 s de tests). |

## Mesures et clôture (Nicolas, 04/10)

| Critère (Q15) | Résultat |
|---|---|
| 2 à 3 annonces réelles de pistes différentes, dossier préparé, ciblage appliqué | 5 dossiers : « Data scientist / IA » (offres 337, 81, 861) et « Data analyst » (offres 222, 141) ; parcours complet jusqu'à « Envoyée » pour 861 et 222 |
| Champs manquants traduits, vrais appels Gemini | Textes du CV importé (49, puis 12 après le nouveau découpage des unités) et champs du profil (stacks des projets…), un appel par geste, après consentement |
| Validation sans écrire de phrase anglaise | Nicolas n'a écrit aucune phrase anglaise. Trois traductions ont été **raccourcies par l'agent** pour tenir dans leur place (« Leading complex projects end to end… », « (written & spoken) » ×2), modifiables par « Modifier » |
| CV anglais sans débordement, « Vérifier mon CV » vert | Les 10 CV ciblés (5 dossiers × FR/EN) rendus sans débordement signalé ; trois lecteurs : 36 à 38 éléments sur 36 à 38 |
| Validation visuelle de Nicolas | « Ça va nous servir de base » : validé comme version de base |

Corrections de la recette (voir les lignes « recette » ci-dessus) : liens de téléchargement non boostés, aperçus à 150 dpi,
découpage en unités (listes, puces, retraits, titres sur deux lignes), geste « Modifier » d'un texte validé, place d'un
texte anglais (colonne, texte suivant), « Vérifier ce CV » dans le dossier, gabarits repliés, parcours du dossier (Q25)
et « À préparer » (Q26).

**Étape validée par Nicolas comme base, avec ces limites** (section 8 du plan) :
- la carte projet « Pilotage d'association sportive » du CV français sort visuellement de son cadre sans être signalée ;
- règles de découpage et de place mises au point sur un seul design (le Canva de Nicolas) ;
- un débordement est signalé mais pas résolu : l'utilisateur raccourcit (idée : proposition automatique plus courte) ;
- gabarits non supprimables (19 au compte de Nicolas, repliés) ;
- envois confirmés sans canal ni révision avant D5 ; « Prête à envoyer » = CV prêt avant D4 ;
- accent grave en trop dans le Canva (formation Jedha), repris en anglais.

Suite : D4 (lettre et message), qui remplit l'étape 2 du dossier.
