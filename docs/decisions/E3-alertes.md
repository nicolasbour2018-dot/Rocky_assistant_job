# E3 — Alertes comme source

Date : 05/10/2026 · Étape : E3 (plan v2, après E4) · Préparation : mode plan, questions à Nicolas (Q1–Q7)

Critère de sortie (plan) : « Au moins une offre Indeed réelle par jour ».

## Constats de départ

| Constat | Source |
|---|---|
| L'ancien Rocky suivait chaque lien d'une alerte, avalait toute erreur (`except Exception: continue`) et jetait les offres sous le seuil | `dashboard/rocky/gmail_service.py` (`_import_links`), tag `rocky-v1-streamlit` ; plan §6 |
| La boîte connectée (une seule) a 170 alertes `job_alert` depuis le 5/09 : Cadremploi 104, eFinancialCareers 44, Hellowork 19. **Aucune alerte Indeed** (la dernière date du 29/08 dans l'archive), **aucune alerte LinkedIn** (100 dans l'archive, toutes sur la 2e boîte de Nicolas), ni Apec ni WTTJ | base de développement (lecture seule, 05/10) ; `backups/rocky-v1-20260924/exports/csv/email_messages.csv` |
| Tous les liens HTML des alertes reçues sont des **redirections de suivi** à jeton personnel (`emails.hellowork.com/clic`, `r.emails*.alertes.cadremploi.fr`, `post.spmailtechnolo.com`) ; seule la partie texte d'eFinancialCareers donne l'adresse directe de l'annonce (`…id24463078`) | base de développement |
| Les liens Indeed de l'archive sont des liens publicitaires (`fr.indeed.com/pagead/clk/dl`, `cts.indeed.com/v3/…`) sans identifiant d'annonce lisible ; Indeed refuse la lecture automatique de ses pages | archive ; validation de C2 (« un lien Indeed refusé ») |
| Le contenu lisible d'une alerte est une suite de **cartes** : intitulé · employeur · lieu · contrat · salaire | corps texte et HTML des alertes (E1, Q5) |
| Les alertes sont les décisions `job_alert` d'E2 (adresses `ALERT_SENDERS`, formes d'objet des relais) | plan §8 (E2 → E3) |
| Moteur commun déjà là : `import_link` (issue typée, raison), `parse_page`, `enriched` ; `record_offer` (offre + pistes + scores en une transaction, idempotent) ; `SqlStore.complete_keys` | `rocky/offres/imports/`, `rocky/offres/usecases.py`, décisions C2 et C6 |

## Décisions métier (Nicolas, 05/10)

| # | Sujet | Décision |
|---|---|---|
| Q1 | Indeed | Nicolas **connecte sa 2e boîte** (alertes LinkedIn, Indeed peut-être). Si aucune alerte Indeed n'y arrive, il crée une alerte Indeed quotidienne sur une boîte connectée. Le critère se constate sur des alertes réelles, jamais simulé. |
| Q2 | Lecture d'une alerte | **La carte d'abord**, toujours, sans réseau ; **puis la fiche si possible** : le lien est lu par `import_link`, dans le planificateur, jamais pour Indeed (refus connu). Chaque lien en échec garde sa raison. Lire un lien de suivi vaut un clic enregistré chez la plateforme : accepté. |
| Q3 | Offres retenues | **Toutes les cartes** deviennent des offres, suggestions de la plateforme comprises (invariant « aucune offre jetée ») ; rattachées à la **meilleure piste**, comme un import (C6, Q10) ; sous le seuil, gardées avec leur motif. |
| Q4 | Historique | **Toutes les alertes déjà collectées, une fois** ; les liens ne sont lus que pour les alertes de **7 jours** au plus. |
| Q5 | Visibilité | **Sur l'alerte** (📬 Messages, vue « Alertes » : « 12 offres (3 nouvelles) · 9 fiches lues · 2 non lues », détail derrière « Pourquoi ? ») **et sur l'offre** (origine « Tirée d'une alerte Hellowork », raison de la fiche non lue). |
| Q6 | Plateformes | Celles **reçues pendant E3** : Cadremploi, Hellowork, eFinancialCareers tout de suite ; LinkedIn et Indeed dès la 2e boîte. Apec et WTTJ seulement si une alerte arrive pendant l'étape, sinon plan §8. Un lecteur s'écrit sur une alerte réelle capturée. Une alerte d'un format inconnu est **signalée**, jamais ignorée. |
| Q7 | Recours | Une fiche non lue (refus, panne, alerte ancienne) se complète par **« Coller la description »** (C7) ; aucune relecture automatique (règle d'arrêt C1 : aucun réessai). |

### Après le premier passage réel (Nicolas, 05/10)

Constat : la reprise de 199 alertes a donné 653 offres et 306 appels réseau, pour beaucoup d'annonces sans rapport ou
périmées (« trop d'appels inutiles »).

| # | Sujet | Décision |
|---|---|---|
| Q8 | Limite | **10 alertes intégrées au plus par jour** et par compte (jour de Paris), les plus récentes d'abord ; les autres attendent le lendemain. Une alerte de **plus de 3 jours ne donne rien** : elle est marquée « trop ancienne », avec sa raison. Remplace Q4 (historique entier, fiches jusqu'à 7 jours). « Pour le moment » : réglage à revoir à l'usage. |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme du code | Sous-paquet `rocky/messages/alerts/` : `model.py` (cartes, lectures, issues des liens, libellés, `ALERTS_VERSION`), `rules.py` (lecteurs purs par plateforme, offre d'une carte), `usecases.py` (passage de lecture). SQL dans `rocky/messages/sql.py` | Même forme que `classification/` et `decisions/` ; plan §3 (« `messages` : alertes emploi ») |
| Lecteur | Choisi par l'**adresse exacte** de l'expéditeur ; HTML lu par BeautifulSoup, texte décodé (`classification.rules.readable`) | Même règle que les plateformes d'E2 (Q16) |
| Identité d'une carte | Identifiant de la plateforme quand le lien le montre (LinkedIn `/jobs/view/<id>` → source `linkedin`, même identité que la veille ; eFinancialCareers `.id<n>`) ; sinon `card-<empreinte>` de (intitulé, employeur, lieu) pliés. Source : nom de source C1 (code, ou hôte : `indeed.com`, `hellowork.com`, `cadremploi.fr`, `efinancialcareers.fr`) | Le lien de suivi change d'une alerte à l'autre : il ne peut pas identifier l'annonce |
| Fiche lue | La carte est complétée par la page (`enriched`) et prend l'**adresse canonique** de la page | Une annonce déjà importée ou trouvée par la veille est retrouvée par son adresse (`SqlStore.find`) |
| Liens | Lus **hors transaction** par `import_link` (`PublicHttp` : hôte public vérifié à chaque redirection, aucun réessai) ; Indeed jamais tenté ; un refus arrête la plateforme pour le passage ; une offre déjà connue complète n'est pas relue (alerte de plus de 7 jours non lue avant Q8 ; depuis Q8, une alerte de plus de 3 jours ne donne rien). Un lien n'est **jamais** journalisé ni mis dans un événement | Règle d'arrêt C1 ; jeton de suivi personnel (plan §8, C2 → E3) |
| Écriture | **Une transaction par alerte** : les offres (`record_offer`, origine `alert`), une ligne par offre (`alert_offers`), la lecture (`alert_readings`) et l'événement `messages.alert_read`. Le verrou des offres du compte (celui de la veille) est essayé en mode transaction : occupé, rien n'est écrit et l'alerte est reprise au passage suivant | Aucune offre sans sa lecture ni l'inverse ; pas de heurt avec une veille en cours (constat C6) |
| Reprise | Le passage lit les messages `job_alert` (décision en vigueur) sans lecture, les plus récents d'abord, dans la limite du jour (Q8 : `alerts_read_since`, lectures `read` depuis minuit à Paris). Une lecture par message (`UNIQUE(message_id)`) : un passage rejoué n'écrit rien. Statut `too_old` ajouté par la migration `0018` (une migration commitée ne se modifie pas) | Idempotence (AGENTS §4) |
| Panne | Une exception inattendue sur une alerte devient une lecture `failed` (« erreur technique »), trace journalisée ; les autres alertes continuent | Aucune exception avalée |
| Liens entre modules | `messages` → `offres` par des fonctions publiques de `rocky/offres/web.py` sur la connexion en cours (`OffresLink`, `rocky/messages/links.py`) ; jamais le SQL d'`offres` | AGENTS §4 ; montage d'E4 |
| Schéma | Migration `0017` : origine `alert` (`job_offers.origin`, `offer_tracks.found_by`) ; `alert_readings` et `alert_offers` en ajout seul | Q5 : ce qu'une alerte a donné se lit dans le schéma |
| Déclenchement | Après chaque classement de l'après-collecte (planificateur) ; commande `rocky-admin alertes <email> [--sans-liens]` | Jamais de réseau dans une requête web (D12) |

## Décisions prises pendant l'implémentation

| Sujet | Décision | Raison |
|---|---|---|
| Lecteurs | Hellowork et Cadremploi : un même lecteur « carte à bouton » (lien d'intitulé, faits, bouton « Voir l'offre ») ; LinkedIn : cartes groupées par `/jobs/view/<n>`, lien public sans paramètre ; eFinancialCareers : la **partie texte** (« Postuler : <adresse>.id<n> »), trois formes | Mesure sur les 199 alertes de la base de développement : 1 397 cartes, aucune alerte de plateforme connue sans carte |
| Faits gardés | Tels qu'écrits : « Competitive », « Selon le profil » restent le texte du salaire (C1 : aucune interprétation) | L'analyse C3 n'y trouve aucun montant |
| Titre et employeur dans `alert_offers` | Copiés de la carte | L'écran des messages ne lit jamais les tables d'`offres` (AGENTS §4) |
| Verrou de la veille | Clé `hashtext(nom || current_schema())`, comme ceux de `messages` | Les alertes l'essaient aussi ; plan §8 (E1 → C6) |
| Panne | Panne du lecteur ou de la lecture d'une fiche → lecture `failed`, visible ; panne de la base → remontée, rien d'écrit, alerte reprise au passage suivant | Une coupure passagère de la base ne doit pas clore une alerte pour toujours |
| `--sans-liens` | Marque définitivement les fiches de l'alerte comme non lues (une alerte est lue une fois) | Réservé au diagnostic (AGENTS §8) |

## Mesures (05/10)

| Contrôle | Résultat |
|---|---|
| Lecteurs sur la base de développement (lecture seule) | 189 alertes lisibles, 1 397 cartes, **658 offres distinctes** ; Hellowork 339 cartes (employeur 337, salaire 151), Cadremploi 324, eFinancialCareers 652 (salaire 631, télétravail 56), LinkedIn 82 ; formats inconnus : JobLeads (3), Meteojob (2), Unesco (3), une lettre d'information (1) |
| Tests | Lecteurs (`test_alerts_rules.py`, 23), cas d'usage sur PostgreSQL (`test_alerts_usecases.py`, 23 : panne injectée après chacune des 4 écritures, veille qui tient les offres, règle d'arrêt, alerte ancienne, offre connue complète, format inconnu, lecteur cassé, aucun lien dans le journal), écran (4), commande (2) |
| Migration `0017` (base de développement) | `upgrade` → `downgrade -1` → `upgrade head` |
| Vérification globale | 1 469 tests verts ; **5 min 50** sous une charge de 15 (VS Code à 250 % du processeur) : mesure à refaire sur une machine calme et sur GitHub |
| **Premier passage réel** (`rocky-admin alertes`, compte de développement, versions `.1`, avant Q8) | 199 alertes : 190 lues, 9 de format inconnu, 0 en échec ; 1 404 cartes, **653 offres nouvelles** ; **306 appels** : Hellowork 201 fiches lues, LinkedIn 36, eFinancialCareers 58 lues et 10 expirées (HTTP 410), **Cadremploi refuse (HTTP 403)** dès la première fiche, ses 100 cartes suivantes non demandées (règle d'arrêt) ; 314 cartes non relues (offre déjà complète), 684 cartes d'alertes de plus de 7 jours sans appel ; 4 fiches Hellowork réduites à un extrait (gardé depuis `.2`). Jugé trop d'appels inutiles par Nicolas : Q8 |
| Migration `0018` (base de développement) | `upgrade` → `downgrade -1` → `upgrade head` |

## Hors E3

Lecture assistée d'une fiche dans un navigateur visible (E5) ; ⚙️ Système (F1) ; alertes Apec et WTTJ si aucune
n'arrive pendant l'étape.
