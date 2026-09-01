# 0003 – MCP Context7 au niveau projet

Date : 2026-09-01. Statut : acceptée.

## Contexte

Les agents ont besoin de la documentation à jour des bibliothèques du projet
(Streamlit, SQLAlchemy, pandas). Les MCPs installés sur la machine d'un
développeur ne suivent pas le clone du dépôt : Nicolas n'en a aucun.

## Décision

Déclarer le serveur HTTP Context7 (`https://mcp.context7.com/mcp`) dans les
deux configurations commitées :

- `.mcp.json` pour Claude Code ; le serveur demande une approbation à la
  première session, c'est voulu ;
- `.codex/config.toml`, section `[mcp_servers.context7]`, pour Codex CLI
  (appliqué sur les projets marqués de confiance).

Sans clé d'API le serveur fonctionne avec une limite de débit basse. Une clé
gratuite peut être ajoutée en local ; elle ne se commite jamais.

## Conséquences

Un seul serveur MCP projet pour l'instant. Tout ajout passe par un nouvel ADR.
