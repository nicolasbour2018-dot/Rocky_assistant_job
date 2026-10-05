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

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Forme du code | Sous-paquet `rocky/messages/alerts/` : `model.py` (cartes, lectures, issues des liens, libellés, `ALERTS_VERSION`), `rules.py` (lecteurs purs par plateforme, offre d'une carte), `usecases.py` (passage de lecture). SQL dans `rocky/messages/sql.py` | Même forme que `classification/` et `decisions/` ; plan §3 (« `messages` : alertes emploi ») |
| Lecteur | Choisi par l'**adresse exacte** de l'expéditeur ; HTML lu par BeautifulSoup, texte décodé (`classification.rules.readable`) | Même règle que les plateformes d'E2 (Q16) |
| Identité d'une carte | Identifiant de la plateforme quand le lien le montre (LinkedIn `/jobs/view/<id>` → source `linkedin`, même identité que la veille ; eFinancialCareers `.id<n>`) ; sinon `card-<empreinte>` de (intitulé, employeur, lieu) pliés. Source : nom de source C1 (code, ou hôte : `indeed.com`, `hellowork.com`, `cadremploi.fr`, `efinancialcareers.fr`) | Le lien de suivi change d'une alerte à l'autre : il ne peut pas identifier l'annonce |
| Fiche lue | La carte est complétée par la page (`enriched`) et prend l'**adresse canonique** de la page | Une annonce déjà importée ou trouvée par la veille est retrouvée par son adresse (`SqlStore.find`) |
| Liens | Lus **hors transaction** par `import_link` (`PublicHttp` : hôte public vérifié à chaque redirection, aucun réessai) ; Indeed jamais tenté ; un refus arrête l'hôte pour le passage ; une offre déjà connue complète n'est pas relue ; une alerte de plus de 7 jours n'est pas lue. Un lien n'est **jamais** journalisé ni mis dans un événement | Règle d'arrêt C1 ; jeton de suivi personnel (plan §8, C2 → E3) |
| Écriture | **Une transaction par alerte** : les offres (`record_offer`, origine `alert`), une ligne par offre (`alert_offers`), la lecture (`alert_readings`) et l'événement `messages.alert_read`. Le verrou des offres du compte (celui de la veille) est essayé en mode transaction : occupé, rien n'est écrit et l'alerte est reprise au passage suivant | Aucune offre sans sa lecture ni l'inverse ; pas de heurt avec une veille en cours (constat C6) |
| Reprise | Le passage lit tout message `job_alert` (décision en vigueur) sans lecture : l'historique (Q4) passe par le même chemin. Une lecture par message (`UNIQUE(message_id)`) : un passage rejoué n'écrit rien | Idempotence (AGENTS §4) |
| Panne | Une exception inattendue sur une alerte devient une lecture `failed` (« erreur technique »), trace journalisée ; les autres alertes continuent | Aucune exception avalée |
| Liens entre modules | `messages` → `offres` par des fonctions publiques de `rocky/offres/web.py` sur la connexion en cours (`OffresLink`, `rocky/messages/links.py`) ; jamais le SQL d'`offres` | AGENTS §4 ; montage d'E4 |
| Schéma | Migration `0017` : origine `alert` (`job_offers.origin`, `offer_tracks.found_by`) ; `alert_readings` et `alert_offers` en ajout seul | Q5 : ce qu'une alerte a donné se lit dans le schéma |
| Déclenchement | Après chaque classement de l'après-collecte (planificateur) ; commande `rocky-admin alertes <email> [--sans-liens]` | Jamais de réseau dans une requête web (D12) |

## Hors E3

Lecture assistée d'une fiche dans un navigateur visible (E5) ; ⚙️ Système (F1) ; alertes Apec et WTTJ si aucune
n'arrive pendant l'étape.
