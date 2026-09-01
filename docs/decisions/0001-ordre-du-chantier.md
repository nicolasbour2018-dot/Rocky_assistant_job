# 0001 – Ordre du chantier qualité

Date : 2026-09-01. Statut : acceptée.

## Contexte

Le code fonctionne mais a grandi sans filet : pas de CI, outillage partiel,
HTML/CSS et SQL dans des chaînes Python. Refactorer sans filet ne se relit pas
(voir aussi le TODO final de `pyproject.toml`).

## Décision

Quatre phases, dans cet ordre, sans chevauchement :

1. Base saine : ruff, mypy et bandit au vert sur tout le périmètre
   (pile de PR en cours).
2. Outillage moderne et CI : uv, `[dependency-groups]` (PEP 735), prek,
   detect-secrets, zizmor, actionlint, pip-audit, Dependabot, GitHub Actions.
   Le choix ty contre mypy se décide ici, sur une mesure de maturité du moment,
   pas de mémoire.
3. Audit de stack : un ADR par remplacement envisagé. Candidats identifiés :
   SQL en f-string de `repository.py` vers un ORM déclaratif ; chaînes
   HTML/CSS vers un vrai templating ; reportlab/docx/LibreOffice vers typst ;
   Streamlit vers un serveur HTTP + htmx. Ce dernier est un changement de
   framework, pas un ajout : le plus gros ADR du projet.
4. Architecture : découpage modulaire (hexagonale ou équivalent), une fois le
   filet CI posé.

## Conséquences

Aucun refactor de fond avant la fin de la phase 2. Chaque remplacement de la
phase 3 passe par un ADR accepté avant le premier commit de code.
