# D4 — Lettre et message

Date : 04/10/2026 · Étape : D4 (plan v2) · Préparation : *grill me* avec Nicolas (Q1–Q20) puis mode plan

Critère de sortie (plan) : « Lettres FR et EN validées sur 3 annonces réelles », précisé par Q19 ci-dessous.

## Constats de départ

| Constat | Source |
|---|---|
| L'étape « 2. Lettre » du dossier dit « à venir » ; « Prête à envoyer » veut dire « CV prêt » | `rocky/candidatures/templates/candidatures/send_step.html`, `rocky/candidatures/rules.py` (`journey`) ; décision D3, Q25 |
| Le profil n'a aucun champ lettre, motivation ou récit | `rocky/profil/model.py`, `rocky/profil/sql.py` |
| La décision « Intéressé » garde un motif et une note libre (C7, D1 Q8), mais aucune fonction publique ne les expose | `rocky/offres/decisions.py`, `rocky/offres/web.py` |
| L'ancien Rocky : gabarit de lettre fixe écrit par Nicolas (récit de reconversion compris), paragraphe « entreprise » généré, lettre complète générée (4–6 paragraphes, « uniquement les faits du JSON »), message d'accompagnement de 180 à 600 caractères pour les champs libres des formulaires, jamais enregistré | `templates/lettre_motivation.txt`, `dashboard/rocky/llm.py`, `dashboard/rocky/letters.py` (historique) |
| Le jugement « parcours très éloigné » venait de l'analyse du profil (`warnings`), pas de la lettre ; aucun prompt de l'ancien Rocky ne fixait de ton | `dashboard/rocky/llm.py` (`analyze_profile_documents`), `docs/archive/rocky-refonte-plan.md` |
| Le texte des lettres n'était pas stocké ; les PDF étaient réécrits au même chemin (D5) ; l'archive A1 garde une cinquantaine de lettres réelles en PDF/DOCX | archive A1 (`application_documents`, `documents/`) |
| Briques réutilisables : rendu HTML → PDF (`system/render.py`), trois lecteurs PDF (`system/pdf_read.py`), glossaire, mémoire et contrôles de traduction (`profil/translation.py`), classement des projets et compétences citées (`candidatures/targeting.py`) | — |

## Décisions métier (grill avec Nicolas, 04/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Message | Le **message d'accompagnement** (2 ou 3 phrases, 180 à 600 caractères, à coller dans le champ libre d'un formulaire), **copiable seulement**. Ni corps d'e-mail, ni note LinkedIn. |
| Q2 | Qui écrit la lettre | **Hybride**, comme l'ancien Rocky : la lettre générique de l'utilisateur, plus un paragraphe « pourquoi vous » par offre. Une version adaptée n'est qu'une **proposition**. Une lettre générique affinée passe mieux les ATS ; le texte généré ne laisse **aucun marqueur typique d'une IA**. |
| Q3 | « Storytelling de préparation » | Le **parcours de préparation du dossier**, commencé en D3 : D4 remplit son étape « 2. Lettre ». |
| Q4 | Lettre et « Prête à envoyer » | Lettre **facultative** par dossier : geste « Pas de lettre pour cette candidature », journalisé. |
| Q5 | Forme | Lettre : **PDF sobre** et **texte copiable**. Message : copiable seulement. |
| Q6 | Lettre générique | **Une par compte**, en blocs nommés (ouverture, parcours, apports, emplacement « pourquoi vous », conclusion), variables `{poste}` et `{entreprise}`. Créée par **import d'un DOCX ou d'un PDF** (ou d'un texte collé), analysé pour remplir les blocs : beaucoup de lettres sont travaillées ailleurs avant, il faut le moins de friction possible. La lettre V1 de Nicolas sert de base par cet import. |
| Q7 | Ce qui est proposé | Chaque paragraphe de la lettre générique est montré **recopié mot pour mot** et, à côté, dans une **version adaptée à l'annonce, sans tricher**. L'utilisateur choisit celle qui entre dans la lettre. Sert de test pour la base (D14). |
| Q8 | Contrôles | Liste déterministe, versionnée dans le code, qui **signale sans bloquer** : marqueurs d'IA (tirets cadratin ou demi-cadratin, Markdown, emoji, guillemets et apostrophes différents de ceux de la lettre de l'utilisateur, formules convenues, liste validée par Nicolas), ton (excuse, manque, « malgré », « éloigné », reconversion présentée comme une faiblesse), faits (chiffre, outil, diplôme ou employeur absent de l'annonce et du profil, variable `{…}` restante, longueur). |
| Q9 | Anglais | La lettre générique est **traduite une fois** par le moteur de D3 (glossaire, mémoire, relecture) et gardée dans le profil. Le « pourquoi vous » et les versions adaptées sont **générés directement en anglais**. Deux boutons FR / EN, sans détection de la langue de l'annonce. |
| Q10 | En-tête et PDF | **Déterministes** : expéditeur (profil), destinataire (« Service recrutement » + entreprise), ville et date, objet, « Madame, Monsieur, » / « Dear Hiring Team, », formule finale, signature. Objet et destinataire modifiables dans le dossier. Pas d'adresse du destinataire (aucune source fiable). PDF A4 d'une page, polices et couleur d'accent du gabarit neutre du CV ; un débordement est une erreur visible. |
| Q11 | Ce qui est gardé | La lettre d'un dossier est une **suite de versions en ajout seul** : texte validé, langue, origine de chaque paragraphe (générique, adaptée, modifiée), texte proposé. La dernière est en vigueur. Rien de non validé n'est stocké. Le PDF est recalculé à la demande (révisions immuables : D5). |
| Q12 | Message | **Proposé par le LLM sur geste**, jamais automatiquement ; mêmes contrôles ; validé ; versions en ajout seul ; affiché dans l'étape Envoi. |
| Q13 | Import de la lettre | Rocky extrait le texte (le modèle ne voit jamais le fichier) ; le modèle **découpe sans réécrire** et place `{poste}` / `{entreprise}` ; un contrôle vérifie que chaque bloc est **mot pour mot** dans le texte d'origine (aux variables près) ; relecture avant enregistrement ; un PDF image est refusé avec sa raison. Le paragraphe propre à l'ancienne entreprise devient l'emplacement « pourquoi vous » ; à défaut, l'emplacement est ajouté avant la conclusion. |
| Q14 | Portée de l'adaptation | Un geste « **Adapter à l'annonce** » = **un appel** : le « pourquoi vous » et une version adaptée de **chaque** paragraphe. Par défaut, l'original est retenu. |
| Q15 | Ce qui part chez Gemini | Avec une case d'accord (comme D3) : intitulé, entreprise, description, résumé, **motif et note de la décision « Intéressé »**, lettre générique, projets et compétences du ciblage avec leurs preuves. Jamais : nom, coordonnées, date de naissance, fichier. |
| Q16 | Fil du dossier | « CV prêt : passer à la lettre » (le dossier reste en préparation) ; « Lettre prête : passer à l'envoi » ou « Pas de lettre » mènent à « Prête à envoyer ». « 2. Lettre ✓ » quand une lettre est validée ou écartée. Le message n'est jamais une condition. |
| Q17 | Modifier | La lettre d'un dossier reste **modifiable à tout moment** : chaque modification **ajoute une version** (origine « modifiée ») sans écraser la précédente ; la dernière sert à l'aperçu, au téléchargement et à l'envoi. Une lettre générique modifiée ne change pas les dossiers : le dossier dit « ta lettre générique a changé depuis » et propose d'en repartir. Une lettre générique anglaise est « à revoir » si son français a changé (D3, Q14). |
| Q18 | Intitulé du poste | Nettoyé **de façon déterministe** pour `{poste}` et l'objet : « H/F », « F/H », « (H/F/X) », contrat et lieu en fin d'intitulé. Liste de motifs testée, sans LLM. |
| Q19 | Critère de sortie | La lettre réelle de Nicolas importée comme lettre générique, découpage validé ; la lettre générique anglaise traduite sans écrire de phrase anglaise ; **3 offres réelles d'au moins 2 pistes** : « Adapter à l'annonce » (vrais appels Gemini, avec l'accord de Nicolas), choix par paragraphe, lettre FR **et** EN validée, PDF d'une page sans débordement, contrôles Q8 sans signal non tranché, message validé, « Vérifier cette lettre » par les trois lecteurs ; validation de Nicolas : « je l'enverrais telle quelle ». |
| Q20 | Modifier après l'envoi | Permis. Le dossier affiche « Envoyée avec la version du … » (version en vigueur à la date d'envoi) ; le lien explicite à la révision envoyée est D5. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Lecture d'un DOCX | `rocky/system/docx_read.py` : paragraphes de `word/document.xml` lus par la bibliothèque standard (`zipfile`, `xml.etree`) ; refus d'un `<!DOCTYPE`, d'une archive ou d'un XML trop gros, d'un fichier qui n'est pas un DOCX | Aucune dépendance ajoutée ; un `<!DOCTYPE` refusé ferme la porte aux entités XML. |
| Lettre générique | `rocky/profil/letter.py` (règles et cas d'usage), table `generic_letters` en ajout seul (la dernière par langue est en vigueur), événement `profil.cover_letter_saved` | Le dossier repère par empreinte que la lettre générique a changé (Q17) ; la lettre est une donnée D14. |
| Traduction de la lettre générique | `translation.propose` reçoit les consignes de l'appelant ; glossaire, mémoire et contrôles de D3 inchangés | « Même moteur » ; aucune copie du code de traduction. |
| Motif de la décision | `offres.web.interested_reason` (fonction publique, connexion de l'appelant) | `candidatures` ne lit pas les tables d'`offres`. |
| Lettre du dossier | Règles pures dans `rocky/candidatures/letter.py` ; tables `application_letters` et `application_messages` en ajout seul ; appels au modèle avant la transaction | Mêmes règles que la sélection du CV (D3) ; une panne de Gemini n'écrit rien. |
| « Pas de lettre » | La ligne « sans lettre » et le passage à « Prête à envoyer » dans **une seule transaction** | Rien de contradictoire si une écriture échoue (critère de D1). |
| Vue de l'étape Lettre | `rocky/candidatures/letter_view.py` (sans FastAPI) : lignes du formulaire, lecture du formulaire, consignes envoyées au modèle | `web.py` ne garde que les routes ; la vue se teste sans HTTP. |
| « Ma version » | Écrire dans « Ma version » la retient, même si un autre bouton radio est coché ; l'origine reste « générique » ou « adaptée » si le texte est inchangé | Aucune correction perdue faute d'avoir coché le bon bouton (aucun JavaScript, décision B4). |
| Lettre envoyée (Q20) | La version en vigueur à la date du dernier passage à « Envoyée » | Lien exact à la révision en D5. |
| PDF de la lettre | Gabarit `rocky/candidatures/letter_pdf/letter.html` : polices et couleur du gabarit neutre, texte justifié **sans césure automatique** | Une césure (« ai-der ») coupe le mot pour les lecteurs de PDF et les ATS (essai navigateur). |
| « Vérifier cette lettre » | `check_cv` avec les faits de la lettre (nom, objet, entreprise, début de chaque paragraphe) ; le document est nommé dans les avertissements | Mêmes trois lecteurs que le CV, sans code dupliqué. |
| Garde-fou XML | `xml.etree` après refus des déclarations `<!DOCTYPE` et `<!ENTITY` (exception `S314` justifiée en commentaire) | Pas de dépendance `defusedxml` ajoutée pour un seul fichier lu. |

## Essai dans un navigateur (Claude, 04/10)

Chromium (Playwright), instance à part : schéma jetable de `test-db`, compte fictif, offre « Data analyst H/F - CDI -
Paris » chez « Exemple Santé », lettre générique fictive, faux modèle de langage.

| Parcours | Résultat |
|---|---|
| « Préparer la candidature » depuis « À préparer » → étape Lettre | Lettre générique remplie pour l'offre (« Data analyst », « Exemple Santé ») ; objet et destinataire proposés |
| « Adapter à l'annonce » (accord coché) | « Pourquoi vous » choisi par défaut, original retenu ailleurs ; signaux affichés : tiret long, « passionné », longueur |
| Validation (ouverture adaptée) | « 2. Lettre ✓ », origine affichée par paragraphe, texte à copier |
| PDF | Une page A4, en-tête et formules ; césure automatique retirée après l'essai |
| « Vérifier cette lettre » | 3 lecteurs, 8 éléments sur 8, accord 100 % |
| « Lettre prête » → Envoi → message proposé puis validé | « Prête à envoyer », lettre téléchargeable dans l'Envoi, message gardé |
| Lettre anglaise sans lettre générique anglaise | Refus expliqué, lien vers « Ma lettre de motivation » |
| Console | Aucune erreur (hors une connexion refusée volontairement au départ) |

## Recette de Nicolas (04/10)

| Constat de Nicolas | Décision |
|---|---|
| « Le découpage semble pas mal » | Import et découpage gardés tels quels. |
| « La version Gemini n'est qu'un copier-coller » | **Révise Q7/Q14** : Gemini écrit **sa propre version** de chaque paragraphe (même rôle, mêmes faits, ses mots, reliée à l'offre, 70 à 130 % de la longueur ; jamais une copie) ; l'utilisateur garde, paragraphe par paragraphe, la sienne ou celle de Gemini. Une proposition identique au paragraphe est signalée « Identique à ton paragraphe ». Libellés « Version de Gemini ». Consignes réglées plus tard bloc par bloc (section 8). `CHECKS_VERSION` passe à `lettre-2026-10-04.2`. |
| « Il faudrait un petit aperçu agréable qui donne une idée concrète de la lettre » | « Aperçu de la lettre » : l'image de la page telle qu'elle sera téléchargée (rendu réel, 110 dpi), depuis le formulaire (rien n'est enregistré, les choix et les propositions reviennent tels quels) ou depuis la lettre validée ; un téléchargement refusé montre aussi l'aperçu. |
| « Je n'ai pas pu télécharger la lettre : elle dépasse sa page d'environ 11 mm » (lettre de 7 paragraphes, environ 2 500 caractères) | Mise en page resserrée : expéditeur et destinataire côte à côte, 9,6 pt, interligne 1,42, marges 16/20/14 mm. Mesure : la même longueur avec un « pourquoi vous » de 900 caractères (3 246 au total) tient ; le débordement reste refusé et nommé (Q10). |
| « Le parcours est juste horrible » | Hors D4 : noté en section 8, à reprendre avec l'écran Candidatures. |

## Mesures et clôture (Nicolas, 04/10)

| Critère (Q19) | Résultat |
|---|---|
| Lettre réelle importée et découpée | Lettre française de Nicolas importée (7 paragraphes, environ 2 500 caractères), découpage jugé bon (« le découpage semble pas mal ») |
| Lettre générique anglaise sans phrase anglaise écrite | Créée par traduction (moteur de D3) |
| 3 offres réelles, au moins 2 pistes, lettre FR et EN validée | **Partiel** : 2 lettres françaises validées sur 2 dossiers (1 paragraphe de Gemini, 1 modifié, 12 de la lettre générique) ; aucune lettre anglaise de dossier validée |
| PDF d'une page, « Vérifier cette lettre » | Premier essai refusé (11 mm de trop) : mise en page resserrée, aperçu ajouté ; essai navigateur : 8 éléments sur 8 lus par les 3 lecteurs |
| Message validé | Non essayé sur une offre réelle (essai navigateur seulement) |
| Validation de Nicolas | « C'est bon je pense, on peut clôturer D4 » : **validée comme base, avec ces limites** (section 8 du plan) |

Limites reprises en section 8 : parcours de la candidature à refaire (D6) ; consignes de Gemini à régler bloc par bloc ;
liste des formules et du ton à valider sur l'usage ; lettre anglaise d'un dossier et message d'accompagnement à éprouver
sur des offres réelles ; PDF daté du jour du téléchargement (D5).

Suite : D5 (révisions et envoi).

