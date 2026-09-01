# Décisions d'architecture (ADR)

Chaque choix structurant du projet vit ici, dans un fichier court et numéroté.
Un ADR ne se réécrit pas : une décision remplacée reçoit le statut
« Remplacée par NNNN », et le nouveau fichier explique ce qui a changé.

Format : Contexte, Décision, Conséquences. Dix lignes suffisent souvent.

| N°   | Titre                              | Statut   |
|------|------------------------------------|----------|
| 0001 | Ordre du chantier qualité          | Acceptée |
| 0002 | Skills agents au niveau projet     | Acceptée |
| 0003 | MCP Context7 au niveau projet      | Acceptée |
| 0004 | Portes de qualité radon et vulture | Acceptée |
| 0005 | Cible de production : le Mac de Nicolas | Acceptée |
| 0006 | Web : FastAPI, Jinja2, htmx, Pico CSS | Acceptée |
| 0007 | Persistance : SQLite seul, ORM SQLAlchemy 2.0, Alembic | Acceptée |
| 0008 | Architecture hexagonale, `src/rocky`, Python 3.13 | Acceptée |
| 0009 | Documents : typst, PDF seul | Acceptée |
| 0010 | Couche LLM : SDK Mistral, pydantic, retries du SDK | Acceptée |
| 0011 | Frontières : pydantic-settings et httpx | Acceptée |
| 0012 | Exploitation : CLI typer, launchd, fin du déploiement HF | Acceptée |
| 0013 | Ordre de migration et stratégie de tests | Acceptée |

## Questions ouvertes pour Nicolas

- Le banc ATS lance quatre extracteurs PDF pour simuler plusieurs analyseurs :
  intention produit à confirmer, ou réduction à deux (0013).
- Le CV Canva : à reproduire à l'identique en typst, ou à redessiner (0009).
- FileVault est-il activé sur le Mac de production (0005) ?
