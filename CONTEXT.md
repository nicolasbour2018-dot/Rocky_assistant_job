# Rocky

Assistant personnel de recherche d'emploi : il collecte des annonces, les note
face à un profil, prépare les dossiers et suit les candidatures, sans jamais
postuler à la place du candidat. Ce fichier est le vocabulaire du projet : un
mot, un sens. Le modèle qui relie ces termes est dans `docs/domaine.md`.

## Comptes et espace personnel

**Candidat** :
La personne qui cherche un emploi et à qui appartient l'espace personnel.
_À éviter_ : utilisateur, user

**Compte** :
L'identité de connexion d'un candidat, reconnue par son adresse e-mail.
_À éviter_ : user, login, tenant

**Espace personnel** :
Tout ce qu'un compte possède : profils, annonces, candidatures, courriels,
veilles. Rien n'en est visible depuis un autre compte.
_À éviter_ : workspace, tenant

**Compte en attente** :
Un compte créé dont l'adresse n'est pas encore vérifiée ; il ne peut pas se
connecter.

**Compte actif** :
Un compte dont l'adresse est vérifiée et qui possède un mot de passe.

**Session** :
Une connexion ouverte pour trente jours, révocable à tout moment.
_À éviter_ : cookie, token

**Jeton de compte** :
Un lien à usage unique et à durée limitée, envoyé par e-mail pour vérifier
une adresse ou réinitialiser un mot de passe.
_À éviter_ : token, lien magique

**Verrouillage** :
Le blocage temporaire de la connexion après cinq échecs consécutifs.
_À éviter_ : ban, blacklist

## Profil

**Profil** :
Un projet de recherche d'un candidat : intitulés visés, domaines, contrats,
lieux, télétravail, salaire minimum, et l'identité à porter sur les documents.
Un compte peut en avoir plusieurs.
_À éviter_ : persona, candidate profile, compte

**Profil actif** :
Le seul profil d'un compte qui alimente le cockpit, la veille et les nouvelles
candidatures.

**Profil en brouillon** :
Un profil dont l'accueil n'est pas terminé ; il ne participe pas à la veille.
_À éviter_ : onboarding, draft

**Langue du profil** :
Le français ou l'anglais, langue des documents et de la correspondance pour
ce profil. Un profil porte ses textes dans les deux langues.
_À éviter_ : locale

**Texte localisé** :
Le résumé, les intitulés et les domaines d'un profil dans une langue donnée.
_À éviter_ : localization, traduction

**Compétence du candidat** :
Un savoir-faire déclaré par le candidat, avec sa catégorie, son niveau et son
caractère central ou non.
_À éviter_ : skill, tag, mot-clé

**Projet** :
Une réalisation validée du candidat, avec son problème, sa stack et son
livrable, qui peut alimenter un cadre du CV.
_À éviter_ : expérience, mission

**Document de profil** :
Un CV ou une lettre de référence d'un profil, dans une langue, versionné ; la
version courante sert aux dossiers.
_À éviter_ : upload, fichier, asset

**Analyse de profil** :
Le préremplissage prudent extrait des documents fournis, à relire par le
candidat avant d'être adopté.
_À éviter_ : extraction, parsing de CV

**Note** :
Un mémo libre du candidat, attaché à un profil.
_À éviter_ : commentaire, post-it

## Annonces et veille

**Annonce** :
Une offre d'emploi normalisée, unique quelle que soit sa source, partagée
entre les profils qui la reçoivent.
_À éviter_ : job, offre (réservé à l'issue d'une candidature), poste

**Source** :
La plateforme d'où vient une annonce, telle que le candidat la nomme.
_À éviter_ : plateforme, site, connecteur, provider

**Collecteur** :
Le service technique qui a réellement livré une annonce quand il diffère de
la source. Exemple : TheirStack collecte Indeed.
_À éviter_ : API, fournisseur

**Veille** :
La collecte périodique des annonces d'un profil sur toutes ses sources,
suivie de leur notation.
_À éviter_ : watch, run, crawl, scraping

**Résultat de veille** :
Le bilan d'une veille : succès, partiel quand une source a échoué mais que
d'autres ont livré, échec quand rien n'a été collecté.
_À éviter_ : status, exit code

**Rattachement** :
Le lien entre un profil et une annonce : « cette annonce est dans le flux de
ce profil ». Il porte la décision du candidat.
_À éviter_ : liaison, profile_job, feed entry

**Flux** :
L'ensemble des annonces rattachées à un profil.
_À éviter_ : feed, liste, inbox

**Fraîcheur** :
L'âge d'une annonce depuis sa publication : nouvelle jusqu'à sept jours,
ancienne de huit à quatorze, expirée au-delà. Elle se déduit de la date et ne
se décide pas.
_À éviter_ : statut NOUVELLE, ANCIENNE

**Complétude** :
Une annonce est complète quand sa description intégrale est connue ; sinon
elle est incomplète et ne peut pas être notée.
_À éviter_ : INCOMPLÈTE, hydratée

**Décision** :
Ce que le candidat a décidé pour une annonce de son flux : à trier, à
étudier, retenue, écartée. Elle est propre à chaque profil.
_À éviter_ : statut de l'annonce, tri, verdict

**Enrichissement** :
L'action volontaire qui va chercher la description intégrale d'une annonce
incomplète auprès d'un collecteur.
_À éviter_ : hydratation, refresh, scraping

**Import par adresse** :
La création d'une annonce à partir de l'adresse d'une page, collée par le
candidat.
_À éviter_ : import URL, scraping

**Doublon** :
Une annonce déjà connue par sa source et son identifiant externe, ou à défaut
son adresse ou son intitulé ; elle n'est jamais recréée.
_À éviter_ : duplicate, collision

**Langue de l'annonce** :
Le français ou l'anglais, détecté dans le texte de l'annonce, que le candidat
peut forcer.
_À éviter_ : locale

**Purge** :
La suppression définitive d'annonces écartées sans candidature.
_À éviter_ : nettoyage, delete

## Correspondance

**Correspondance** :
La note, de zéro à cent, d'une annonce pour un profil, calculée par des règles
fixes et expliquée critère par critère. Le modèle de langage n'y participe
jamais.
_À éviter_ : match, matching, score IA, pertinence

**Barème** :
Les critères et leurs poids qui produisent la correspondance, identifiés par
une version.
_À éviter_ : weights, algorithme, moteur

**Détail** :
La contribution de chaque critère à la correspondance, avec sa raison.
_À éviter_ : breakdown, explication

**Atout** :
Un point fort nommé dans le détail.
_À éviter_ : strength, force

**Manque** :
Un point faible nommé dans le détail.
_À éviter_ : gap, faiblesse, lacune

**Seuil de veille** :
La correspondance minimale pour qu'une annonce collectée reste dans le flux.
_À éviter_ : threshold, filtre

**Historique de correspondance** :
Toutes les notes passées d'un couple profil-annonce, avec le barème employé ;
on n'y efface rien.
_À éviter_ : log, audit

## Candidature

**Candidature** :
Le dossier et le suivi d'un profil pour une annonce, unique par couple.
_À éviter_ : application, postulation, dossier (réservé aux documents)

**Dossier** :
Les documents courants d'une candidature : le CV ciblé et la lettre, en PDF.
_À éviter_ : package, pièces jointes

**CV ciblé** :
Le CV du profil adapté à une annonce, sans invention : seuls les projets et
compétences validés y entrent.
_À éviter_ : CV généré, tailored CV

**Lettre** :
La lettre de motivation d'une candidature, rédigée puis relue par le candidat
avant rendu.
_À éviter_ : cover letter, courrier

**Étape** :
Où en est une candidature : préparée, prête à envoyer, envoyée, accusé de
réception, en cours, entretien, test technique, offre, refus, abandonnée. Les
étapes sont ordonnées.
_À éviter_ : statut, state, stage

**Offre** :
L'issue positive d'une candidature : l'employeur propose le poste.
_À éviter_ : offre d'emploi (dire annonce)

**Abandonnée** :
Une candidature que le candidat a close sans issue de l'employeur.
_À éviter_ : écartée (réservé à la décision), retirée

**Étape terminale** :
Offre, refus ou abandonnée : plus rien ne s'y automatise.
_À éviter_ : clôturée, fermée

**Événement** :
Toute création ou changement d'étape d'une candidature, daté et attribué à son
origine.
_À éviter_ : log, historique, audit

**Origine** :
Ce qui a provoqué un événement : le candidat, Gmail, Gmail confirmé par le
candidat, la confirmation d'envoi, l'assistant, une annulation.
_À éviter_ : source (réservé aux annonces), auteur

**Annulation** :
Le retour en arrière du dernier événement d'une candidature, lui-même tracé
comme événement.
_À éviter_ : undo, rollback, correction

**Préremplissage supervisé** :
L'ouverture du formulaire de l'employeur avec les champs visibles remplis et
les documents joints ; le candidat relit et envoie lui-même. Rocky ne soumet
jamais.
_À éviter_ : auto-apply, soumission, bot

## Courriel

**Courriel** :
Un message lu dans une boîte Gmail du candidat, en lecture seule, dont Rocky
ne garde que l'expéditeur, le sujet et un extrait.
_À éviter_ : mail, email, message

**Classement** :
La catégorie donnée à un courriel par des règles fixes : offre, refus, test
technique, entretien, accusé de réception, en cours, alerte d'annonces, retour
de candidature, bruit.
_À éviter_ : classification, label, tag

**Confiance** :
La certitude, de zéro à un, d'un classement ou d'un rapprochement.
_À éviter_ : score, probabilité

**Rapprochement** :
L'association d'un courriel à une candidature par le nom de l'employeur seul.
_À éviter_ : matching (réservé à la correspondance), lien

**Traitement** :
Ce qu'est devenu un courriel : à relire, appliqué automatiquement, ignoré
automatiquement, approuvé, ignoré, importé, classé.
_À éviter_ : processing state, statut

**Triage** :
Le passage de tous les courriels à relire par le classement, le rapprochement,
puis la décision de traitement.
_À éviter_ : sync, scan, analyse

**Alerte d'annonces** :
Un courriel qui contient des liens vers des annonces ; ses liens peuvent être
importés.
_À éviter_ : newsletter, job alert

**Classement manuel** :
Un classement fixé par le candidat ; le triage ne le remet jamais en cause.
_À éviter_ : override, correction

## Documents et analyses

**Rendu** :
La production d'un PDF à partir d'un modèle de document et d'un contenu.
_À éviter_ : génération, export, compilation

**Modèle de document** :
Le gabarit d'une lettre ou d'un CV, indépendant du contenu qu'il reçoit.
_À éviter_ : template, layout

**Simulation ATS** :
L'estimation locale de la lisibilité d'un dossier par un logiciel de
recrutement, avec ses atouts et ses alertes.
_À éviter_ : score ATS réel, prédiction

**Banc de robustesse** :
La lecture d'un même CV par plusieurs extracteurs indépendants pour mesurer
ce qui diverge entre eux.
_À éviter_ : ATS V3, benchmark

**Exigence** :
Une compétence demandée par une annonce, avec son importance : obligatoire,
souhaitée ou simplement détectée.
_À éviter_ : requirement, prérequis

## Assistant

**Assistant** :
Le chat de la mascotte Rocky, qui lit l'espace personnel et propose des
actions.
_À éviter_ : bot, agent, IA, chatbot

**Action proposée** :
Une modification suggérée par l'assistant, lisible et à confirmer par le
candidat avant toute écriture.
_À éviter_ : commande, tool call
