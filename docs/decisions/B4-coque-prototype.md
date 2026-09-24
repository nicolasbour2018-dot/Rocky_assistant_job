# B4 — Coque web et prototype de tri

Date : 25/09/2026 · Étape : B4 (plan v2) · Préparation : *grill me* puis mode plan

Critère de sortie : « Décision explicite : HTMX confirmé ou plan B (NiceGUI). »

## Comment se prend la décision

Nicolas utilise le prototype (trier 20 offres au clavier, ouvrir des fiches, un « Pourquoi ? », essai sur téléphone)
et juge cinq critères. **Un seul critère en échec suffit** pour construire un prototype NiceGUI avant de trancher.

| # | Critère |
|---|---|
| a | Tri au clavier fluide : une décision, l'offre suivante, sans rechargement visible |
| b | Liste et fiche latérale mises à jour sans recharger la page |
| c | « Pourquoi ? » ouvert à la demande |
| d | Réponse ressentie instantanée (< 150 ms en local) |
| e | Pas de JavaScript maison au-delà des raccourcis clavier |

## Décisions (grill me avec Nicolas, 25/09)

| Sujet | Décision |
|---|---|
| Sort du prototype | Amorce de C7 : gabarits, CSS et règles de décision gardés ; données factices et décisions en mémoire isolées dans des fichiers jetables (`rocky/offres/prototype.py`, `prototype_offers.json`) |
| Style | CSS écrit à la main, variables ; thème clair ou sombre selon le système ; sobre et dense (façon Linear), police du système, une couleur d'accent, « Rocky 🐾 » en tête. Première version, à revoir plus tard si besoin |
| HTMX | Copie officielle servie par Rocky (aucun CDN) ; pas d'Alpine.js ; un petit script pour les raccourcis clavier |
| Navigation | Barre latérale sur ordinateur ; **téléphone soigné** (usage prévu depuis le VPS) : barre du bas 🏠 🔎 📝 📬 + « Plus » (📈 👤 ⚙️) |
| Pages non encore construites | État vide explicatif (ce que la page fera, l'étape qui l'apporte) ; 🏠 Aujourd'hui remplace l'accueil provisoire de B3 |
| Tiroir Rocky 🐾 | Bouton placé dans la coque, tiroir vide jusqu'à F1 |
| Pages de compte | Style de la coque, centrées, sans navigation |
| Contenu du prototype | Mode tri, liste compacte avec fiche latérale, « Pourquoi ? », annulation sur plusieurs niveaux |
| Touches | `i` intéressé · `e` écarté · `p` plus tard · `u` annuler · `j`/`k` suivante/précédente · `w` Pourquoi ? · `o` annonce · `?` aide ; boutons tactiles sur téléphone |
| Motifs | **Obligatoires pour toute décision** (jeu de données complet et homogène), **plusieurs possibles** : touches 1–9 pour cocher, `Entrée` pour valider, `Échap` pour revenir ; « autre » exige une précision écrite |
| Langue des données | Codes anglais seulement dans les données (`rejected`, `too_senior`…), colonnes anglaises ; libellés français à l'écran uniquement ; seule exception, le texte libre de précision |
| Ordre de la file | Score décroissant ; les offres **sous le seuil** sont hors de la file, accessibles par un filtre volontaire ; un compteur « N sous le seuil → » signale leur existence |
| Seuil du prototype | 60 (le vrai seuil se fixe au calibrage C5) |
| Ouverture de 🔎 Offres | Mode tri s'il reste des offres à examiner, sinon la liste (« Tout est trié ») |
| Score | Entier sur 100, toujours accompagné de l'indice de confiance (faible / moyenne / élevée) |
| « Pourquoi ? » | Maquette du format C4 : intitulé ↔ pistes, compétences trouvées et manquantes, lieu et télétravail, contrat, salaire ou TJM, éliminatoires à part ; verdict et preuve citée par composante ; mention « score provisoire » |
| Liste | Colonnes score · intitulé · entreprise · lieu · source · ancienneté · décision ; filtres piste, décision (défaut « à examiner »), sous le seuil, incomplètes ; fiche en plein écran sur téléphone |
| Fiche | Titre et score → synthèse (date limite, éliminatoires, compétences trouvées et manquantes) → faits → boutons → « Pourquoi ? » replié → description → lien d'origine |
| Changer une décision | Possible, avec le même choix de motifs (en C7 : nouvelle décision ajoutée à l'historique) |
| Annulation | Plusieurs niveaux, dans l'ordre inverse |
| Stockage des décisions | En mémoire, perdues au redémarrage ; bouton « remettre à zéro » |
| Données | 30 offres **réelles** de l'archive A1 (dépôt public accepté) : mélange volontaire (bien et mal notées, complètes et incomplètes, plusieurs sources, un TJM, une offre ancienne) ; faits de l'annonce seulement, ni décisions ni candidatures ; e-mails et téléphones retirés du texte |
| Pistes provisoires | **IA / Machine learning** et **Data analyst** (plus différenciantes que IA/ML et Data scientist, qui se recoupent) ; les vraies pistes arrivent en B5 |
| Tests | HTML via `TestClient` dans la vérification ; essai dans un vrai navigateur par Claude puis par Nicolas ; tests de navigateur automatisés en F2 |

### Motifs (codes stockés → libellés affichés)

| Décision | Motifs |
|---|---|
| `interested` — Intéressé | `target_job` métier visé · `skills_match` compétences alignées · `company_appeal` entreprise ou secteur attirant · `location` lieu ou télétravail · `salary` salaire · `growth` évolution ou apprentissage · `other` autre |
| `rejected` — Écarté | `not_the_job` pas le métier · `too_senior` trop senior · `too_junior` trop junior · `missing_skills` compétences manquantes · `location` lieu ou télétravail · `contract` contrat · `salary` salaire · `company` entreprise ou secteur · `other` autre |
| `later` — Plus tard | `reread` à relire à tête reposée · `missing_info` infos manquantes · `application_to_prepare` candidature à préparer · `distant_deadline` date limite lointaine · `other` autre |

## Décisions techniques

| Sujet | Décision | Raison |
|---|---|---|
| Emplacement | Coque dans `rocky/system/` (`shell.py`, `static/`, `templates/`) ; tri dans `rocky/offres/` (`decisions.py` et gabarits gardés, `prototype.py` jetable) | Le module `offres` naît ; ce qui sera repris en C7 est séparé de ce qui sera supprimé. |
| Scores provisoires | Calculés par `docs/procedures/b4-prototype/build_offers.py`, pas dans `rocky/` | Ce calcul n'est pas le scoring C4 et ne doit pas pouvoir être repris par erreur. |
| Échanges | Le serveur renvoie des fragments HTML ; HTMX les place dans la page ; navigation en `hx-boost` | Pas d'état côté client (critère e). |
| Dépendances | Aucune nouvelle dépendance Python ; HTMX téléchargé une fois, version et empreinte notées | `StaticFiles` vient de Starlette. |

## Mesures et décision

### Mesures de Claude (25/09/2026)

| Contrôle | Résultat |
|---|---|
| Tests automatiques | 154 verts (coque, pages vides, statiques, pages de compte, règles de décision, données, parcours HTMX) |
| HTMX | 2.0.11, copie de jsDelivr ; empreinte SHA-256 `d6fdc75f…4000f717` identique à celle d'unpkg |
| (a) Tri au clavier, Chromium (Playwright) | `e` → motifs → `2`, `5` → `Entrée` : offre suivante, compteur mis à jour, **aucun rechargement** (une seule navigation) ; `u` rend l'offre ; `w` ouvre le « Pourquoi ? » |
| (b) Liste et fiche | filtres et fiche sans rechargement ; l'URL garde les filtres ; fiche en plein écran sur téléphone |
| (c) « Pourquoi ? » | chargé au premier clic seulement (`hx-trigger="click once"`) |
| (d) Temps de réponse | 78 requêtes du tri (motifs, décision, Pourquoi ?, fiche, annulations, liste) : médiane **7,9 ms**, 90 % sous **16,4 ms**, maximum 61,5 ms (première requête) — application sur le poste, base dans Docker |
| (e) JavaScript maison | `rocky.js` seulement : raccourcis `data-key` (≈ 40 lignes), aucun état côté client ; menus et tiroir en `popover` natif, « Pourquoi ? » et description en `details` |
| Téléphone (390 px) | barre du bas 🏠 🔎 📝 📬 + « Plus », boutons ≥ 44 px, motifs en pastilles, fiche plein écran, touches masquées |

Points d'attention relevés :
- **Frappes pendant un échange** : une touche tapée avant l'arrivée d'un fragment (par exemple `e` puis `2` en moins de
  quelques millisecondes, ou `w` pendant une annulation) s'applique à l'ancien contenu et se perd. Invisible en local ;
  à surveiller sur le VPS (latence réseau). Parade possible sans JavaScript de plus : envoyer les panneaux de motifs
  avec la carte.
- Les descriptions de l'archive contiennent du Markdown (`## **…**`) affiché tel quel (mise en forme : C3).

### Décision de Nicolas

Essai de Nicolas le 25/09/2026, scénario complet (les 8 étapes cochées, téléphone compris), consigné dans la
grille `docs/procedures/b4-prototype/grille-essai.html` (artifact privé, base `evaluations/b4`) :

| # | Verdict | Note de Nicolas |
|---|---|---|
| a | ✔ tenu | « Finalement très agréable avec les raccourcis clavier, c'est original mais pas inintéressant. » |
| b | ✔ tenu | — |
| c | ✔ tenu | — |
| d | ✔ tenu | « Franchement, à un niveau humain, le ressenti est instantané. » |
| e | ✔ tenu | — |

**Décision : HTMX confirmé (D6).** Le plan B (NiceGUI) n'est pas construit.

Bug signalé par Nicolas, corrigé avant la clôture : après « Revenir », les boutons de décision ne répondaient plus.
Cause : HTMX fait hériter `hx-swap` ; le bouton « Revenir », placé dans le formulaire de motifs
(`hx-swap="outerHTML"`), remplaçait la zone `#decision-area` au lieu de son contenu, et les boutons revenus visaient une
zone disparue. Correction : `hx-swap="innerHTML"` explicite sur tout ce qui cible `#decision-area` ; test de
non-régression (qui échoue sans la correction) ; vérifié dans Chromium (trois allers-retours `e` → `Échap`).
Leçon pour C7 : déclarer `hx-swap` explicitement sur tout élément placé dans un conteneur qui en porte un autre.
