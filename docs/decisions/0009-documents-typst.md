# 0009 – Documents : typst, PDF seul

Date : 2026-09-01. Statut : acceptée.

## Contexte

Quatre chemins de génération : lettre en DOCX par `python-docx`, la même
lettre en PDF par `reportlab`, CV anglais reconstruit par `reportlab` après
traduction avec une heuristique de titres, CV français par rédaction de
zones du PDF Canva avec `PyMuPDF`. LibreOffice est lancé en sous-processus
pour convertir DOCX en PDF, avec un profil isolé par conversion. Un troisième
rendu HTML sert d'aperçu. Les polices Poppins et Questrial sont livrées dans
`assets/fonts/` et jamais utilisées.

Alternatives pesées : WeasyPrint (réutilise Jinja2, mais dépendances système
pango et cairo, typographie inférieure) ; conserver et rationaliser.

## Décision

typst, via le paquet Python `typst` qui embarque le compilateur, sans
dépendance système. Un template par document : lettre (FR et EN, même
template, contenu en variables) et CV (FR et EN). Le contenu reste éditable
dans Rocky avant compilation. Les polices du projet sont passées au
compilateur.

Sortie PDF seule. Le DOCX est abandonné ; à rouvrir seulement si un recruteur
l'exige. L'aperçu affiche le PDF produit, le rendu HTML disparaît.

## Conséquences

- `python-docx`, `reportlab`, `PyMuPDF` côté génération et LibreOffice
  disparaissent.
- Le PDF Canva n'est plus la source du CV : le CV devient un document typst
  construit depuis le profil. La rédaction par zones (`cv_tailoring.py`) et
  l'heuristique de titres disparaissent.
- Question ouverte pour Nicolas : reproduire son CV Canva à l'identique en
  typst, ou le redessiner ?
