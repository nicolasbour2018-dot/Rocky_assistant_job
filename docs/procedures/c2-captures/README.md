# C2 — Captures des pages d'annonce

Décision : `docs/decisions/C2-import-url.md` (Q5). Produit les jeux de données enregistrés des tests de l'import
(`tests/offres/imports/data/`, origine de chaque fichier dans son `README.md`).

À refaire quand une plateforme change sa page d'annonce (un test d'import ne reflète plus la réalité). Chaque
capture fait de **vrais appels** : avec l'accord de Nicolas, une fois, jamais en boucle.

## 1. Capturer

Pages publiques, sans clé, depuis le poste. Les réponses sont écrites **hors du dépôt**, avec leur statut et leurs
en-têtes anti-robot :

```sh
uv run python docs/procedures/c2-captures/capture.py ~/rocky-captures-c2 <url> [<url>…]
```

Les URL sont lues dans l'ordre, avec une pause de 2 s par site. **Au premier refus (HTTP 403, 429, défi), le script
s'arrête et on en parle à Nicolas** avant toute autre tentative (règle d'arrêt de C1, Q5). Mettre en dernier une
page qui risque d'être refusée.

## 2. Préparer les jeux de test

```sh
uv run python docs/procedures/c2-captures/prepare.py ~/rocky-captures-c2 [<autre dossier>…]
```

`prepare.py` range chaque page dans `tests/offres/imports/data/<source>/` (`posting.html` si elle porte un
`JobPosting`, sinon `page.html`) et ne garde que ce que lit l'import : blocs JSON-LD, `<title>`, lien `canonical`,
balises `og:`, corps visible. Il retire les autres scripts, styles, images et formulaires ; la carte « auteur de
l'offre » de LinkedIn et les liens de profils ; les vidéos de salariés de WTTJ (prénoms) ; il neutralise les
adresses e-mail. La page Apec (coquille Angular sans annonce) est ignorée : un lien Apec est lu par le détail
public, dont les jeux viennent de C1.

Relire ensuite les pages (aucun nom de personne, aucune adresse, aucun jeton), mettre à jour les valeurs attendues
des tests et la date de capture dans `tests/offres/imports/data/README.md`.

## Mesures du 25/09/2026

| Page | Statut | Constat |
|---|---|---|
| Fiche LinkedIn (visiteur) | 200 | `JobPosting` ; description **échappée deux fois** (`&lt;p&gt;`) ; carte « auteur de l'offre » nominative |
| Fiche Welcome to the Jungle | 200 | `JobPosting` + `FAQPage` ; `jobLocation` en liste ; pas d'`identifier` ; vidéos de salariés |
| Fiche Recruitee (site carrière) | 200 | `JobPosting` ; `identifier.value` numérique ; `baseSalary` et `validThrough` à `null` |
| Fiche Hellowork | 200 | `JobPosting` parmi 4 blocs ; `baseSalary` sans montant ; `estimatedSalary` = estimation de Hellowork (ignorée) |
| Recherche Hellowork | 200 | Aucun `JobPosting` : cas « page sans annonce » |
| Fiche Apec | 200 | Coquille Angular, texte de connexion seulement (`x-datadome: protected`, non refusée) |

Aucun refus.
