# ATS V3 — méthode, provenance et limites

ATS V3 est un banc de test indépendant des analyses ATS V1 et V2. Il part du
fichier PDF ou DOCX réellement envoyé, ne consulte pas les compétences du
profil Rocky, ne corrige pas silencieusement le texte extrait et n'utilise pas
de LLM pour déclarer une compétence présente.

## Moteurs d'extraction

Pour un PDF, trois moteurs sont exécutés séparément :

| Moteur | Rôle dans V3 | Licence |
| --- | --- | --- |
| [pypdf](https://github.com/py-pdf/pypdf) | extraction PDF brute et observation des coordonnées/images | BSD-3-Clause |
| [pdfminer.six](https://github.com/pdfminer/pdfminer.six) | extraction orientée analyse de mise en page | MIT |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) / PDFium | extraction par le moteur PDFium et rendu de l'aperçu | Apache-2.0 ou BSD-3-Clause, plus les licences des binaires PDFium |

Pour un DOCX, Rocky compare `python-docx` (MIT) à une lecture indépendante du
contenu OOXML avec les bibliothèques ZIP/XML de Python. Cette voie ne dispose
donc que de deux moteurs ; le PDF reste le format de première classe.

`pdftotext -layout` de Poppler peut être affiché comme diagnostic local
supplémentaire. Il ne participe jamais aux scores et reste facultatif. PyMuPDF
n'a pas été retenu pour éviter d'introduire sa contrainte AGPL/commerciale dans
Rocky.

### Parseurs de CV spécialisés évalués mais non intégrés

| Projet | Constat au 13 août 2026 | Décision |
| --- | --- | --- |
| [OpenResume](https://github.com/xitanggg/open-resume) | parseur PDF.js intéressant et actif, mais application TypeScript/Next.js sous AGPL-3.0 | non embarqué dans le monolithe Python ; ses idées de comparaison visuel/texte restent une référence |
| [pyresparser](https://github.com/OmkarPathak/pyresparser) | GPL-3.0, version 1.0.6 et dépendance déclarée `spacy>=2.1.4`, issue d'une chaîne Python ancienne | écarté pour compatibilité et maintenance avec Python 3.13 |
| [LeverParser / pyresume](https://github.com/wespiper/pyresume) | MIT et API Python prometteuse, mais seulement deux commits visibles, cinq étoiles et une feuille de route encore pré-1.0 | écarté de ce premier banc robuste ; à réévaluer quand le projet aura davantage de versions et de validation indépendante |

La V3 préfère donc trois moteurs PDF établis et réellement distincts, suivis
d'une structuration commune, courte et auditable. Cette structuration commune
ne rend pas les extractions identiques : les divergences du texte fourni par
chaque moteur sont conservées et mesurées.

## Étude d'ATS Screener

Le projet étudié est
[sunnypatell/ats-screener](https://github.com/sunnypatell/ats-screener), commit
`4bc7e4d3af870e9634bab5fc12f7e850da43371a` consulté le 13 août 2026. Il est
distribué sous licence MIT, copyright 2026 Sunny Patel.

Les idées retenues sont :

- confronter parsing, rubriques structurées et matching de mots-clés ;
- représenter plusieurs philosophies approximatives, des stratégies strictes
  et littérales aux stratégies plus tolérantes ;
- vérifier séparément coordonnées, sections, expériences, dates, compétences
  et lisibilité de la mise en page ;
- afficher un avertissement explicite : une simulation ne reproduit pas un ATS
  propriétaire ni les réglages propres à une entreprise.

Aucun fichier TypeScript, composant d'interface, tokenizer, taxonomie, prompt
ou jeu de poids d'ATS Screener n'a été copié. Les six benchmarks Rocky sont une
réimplémentation Python minimale et transparente. Leurs noms sont toujours
suffixés par « -like » dans l'interface.

## Extraction structurée commune

Chaque texte extrait passe par les mêmes règles génériques français/anglais.
Rocky cherche : nom, coordonnées, titre professionnel, rubriques, expériences,
entreprises, dates, formation, établissements, compétences, langues,
certifications et projets. Ces règles ne contiennent ni le nom de Nicolas ni
des adaptations à son CV.

La taxonomie de compétences générique déjà utilisée pour analyser les annonces
Rocky est réutilisée des deux côtés. Elle sert seulement à reconnaître ce qui
est présent dans les textes du CV et de l'annonce ; les compétences enregistrées
dans le profil candidat ne sont jamais injectées.

## Indicateurs

### Robustesse de parsing

Pour chaque parseur, une qualité d'extraction mesure la quantité de texte, les
caractères isolés, les caractères anormaux, les rubriques standard, les
coordonnées et les dates. La cohérence inter-parseurs combine les intersections
de mots et des champs structurés.

`robustesse = 55 % qualité moyenne + 45 % cohérence inter-parseurs`

### Correspondance avec l'annonce

- **Termes exacts** : la formulation vue dans l'annonce est retrouvée par une
  majorité de parseurs.
- **Couverture lexicale** : terme exact ou variante explicite de la taxonomie,
  reconnue par une majorité de parseurs.
- **Obligatoires** : même mesure limitée aux exigences marquées obligatoire,
  indispensable, requise ou équivalent dans leur phrase.
- **Mots-clés** : fréquence déterministe des termes significatifs de l'annonce,
  sans stopwords.
- **Sémantique** : petite table d'équivalences explicites, calculée uniquement
  parmi les compétences absentes lexicalement. Elle n'augmente jamais la
  couverture lexicale.

La note synthétique secondaire est :

`45 % robustesse + 40 % couverture lexicale + 15 % mots-clés`

Elle n'est ni une probabilité de sélection ni le résultat principal.

### Benchmarks « ATS-like »

Les six lignes Workday-like, Taleo/Oracle-like, iCIMS-like, Greenhouse-like,
Lever-like et SuccessFactors-like pondèrent seulement les indicateurs déjà
visibles : parsing, exact/lexical et structure. Elles permettent de tester la
sensibilité du CV à plusieurs philosophies, pas de prédire un éditeur réel.

## Limites connues

- Aucun OCR n'est appliqué. Un CV scanné échoue volontairement de façon visible.
- La détection des expériences et rubriques est heuristique et peut manquer un
  titre très créatif ou une mise en page non standard.
- Une compétence hors taxonomie reste visible dans les mots-clés et les textes
  bruts mais pas dans la matrice de compétences.
- Les trois bibliothèques PDF n'implémentent pas trois ATS complets ; elles
  offrent trois chaînes d'extraction indépendantes pour mettre en évidence les
  divergences de lecture.
- Le rendu visuel intégré affiche la première page du PDF. Le texte brut couvre
  toutes les pages.
- Les résultats V1, V2 et V3 ne sont pas des scores interchangeables : V1/V2
  analysent aussi la lettre, tandis que V3 isole la robustesse du CV et son
  exposition explicite aux exigences de l'annonce.
