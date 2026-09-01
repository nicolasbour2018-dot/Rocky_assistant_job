# 0002 – Skills agents au niveau projet

Date : 2026-09-01. Statut : acceptée.

## Contexte

Nicolas code avec Claude Code et Codex CLI. Claude Code découvre les skills
dans `.claude/skills/` et suit les liens symboliques ; Codex les découvre dans
`.agents/skills/` (standard ouvert « agent skills »). Deux skills publiques ont
été évaluées pour aider un développeur débutant sur du Python moderne.

## Décision

- `python-expert` (awesome-llm-apps) : rejetée. La skill a été supprimée du
  dépôt source (absente de l'arbre HEAD, vérifié le 2026-09-01) ; skills.sh en
  sert une copie morte. C'était un persona générique, redondant avec
  `AGENTS.md` et `.claude/rules/`.
- `modern-python` (Trail of Bits) : adoptée, vendorée seulement en ouverture de
  la phase 2 (ADR 0001). Copier `SKILL.md` et `references/` dans
  `.agents/skills/modern-python/`, puis lier `.claude/skills/modern-python`
  vers ce dossier : une seule copie sert les deux outils. Ne pas installer le
  plugin complet : ses hooks remplacent `pip` et `python` par des shims uv.
- Les conventions du projet restent dans `AGENTS.md` et `.claude/rules/` ;
  les skills servent aux workflows outillés, pas aux conventions.

## Conséquences

Jusqu'à la phase 2, aucun agent ne reçoit d'instruction uv ou ty : l'état
documenté reste pip + venv + mypy. Au moment du vendoring, fusionner la config
ruff de la skill à la main dans `pyproject.toml` : celle du projet est plus
précise que celle de la skill.
