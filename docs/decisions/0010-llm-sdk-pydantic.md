# 0010 – Couche LLM : SDK Mistral, pydantic, retries du SDK

Date : 2026-09-01. Statut : acceptée.

## Contexte

`llm.py` utilise le SDK officiel en mode JSON, mais recrée un client à chaque
appel, sans timeout ni retry (sauf un retry correctif dans
`translate_blocks`), et revalide chaque champ à la main après `json.loads`.
Neuf sites d'appel construisent leur propre client. Deux choses sont à garder
telles quelles : l'hygiène des erreurs (`_safe_failure_detail` ne conserve
qu'un code HTTP) et le test qui vérifie qu'aucune clé ne fuit.

Alternatives pesées : `instructor` (une dépendance de plus pour ce que
pydantic et le SDK font déjà) ; `pydantic-ai` (framework d'agents,
surdimensionné pour de l'extraction et de la traduction).

## Décision

Un seul client Mistral, construit par la composition et injecté derrière un
port du domaine. Timeout explicite par appel (`timeout_ms`). Retry avec
backoff par le `RetryConfig` du SDK lui-même, sur les erreurs réseau, 429 et
5xx ; jamais sur une erreur 4xx d'entrée. `tenacity` avait été envisagé ici ;
le SDK fournit déjà le mécanisme (vérifié dans sa documentation), il n'est
donc retenu que pour httpx (0011).

Sorties structurées : un modèle pydantic par réponse attendue, dont le schéma
JSON est passé au SDK en `response_format` de type `json_schema`, validé une
fois côté Python. Les prompts vivent dans des fichiers versionnés sous
`adapters/mistral/prompts/`, pas dans des f-strings.

Pas de framework d'agents. Le chat de la mascotte garde le streaming.

## Conséquences

- `_safe_failure_detail` et le test de non-fuite migrent tels quels.
- Le retry correctif de `translate_blocks` devient un validateur pydantic qui
  déclenche le retry.
- Le modèle reste configurable, `mistral-small-latest` par défaut.
- Aucune dépendance nouvelle pour cette couche.
