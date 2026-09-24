# Rocky

Rocky est un assistant personnel de recherche d'emploi : il collecte des offres, les classe avec un score
déterministe et explicable, prépare les candidatures et suit les réponses Gmail en lecture seule. Il ne postule
jamais à la place de l'utilisateur.

> **Refonte en cours** sur la branche `refonte`, selon [`docs/rocky-refonte-plan-v2.md`](docs/rocky-refonte-plan-v2.md).
> L'ancien Rocky (Streamlit) reste l'outil quotidien jusqu'à la bascule : il est lancé depuis le worktree
> `../Rocky_v1` (tag `rocky-v1-streamlit`), jamais depuis ce dépôt. Les règles des agents sont dans
> [`AGENTS.md`](AGENTS.md).

## Prérequis

- Docker (Docker Desktop sur macOS) ;
- [uv](https://docs.astral.sh/uv/) (`brew install uv`) pour l'environnement local et l'éditeur.

Le dépôt vit dans `~/Developer/`, **hors iCloud**.

## Installation

```bash
uv sync                  # .venv avec Python 3.13 géré par uv et les versions de uv.lock
cp .env.example .env     # puis renseigner les mots de passe PostgreSQL et le SMTP
```

## Commandes

| Besoin | Commande |
|---|---|
| Vérification globale (format, lint, types, tests) | `docker compose run --rm --build check` |
| Tests seuls, depuis le poste | `docker compose up -d test-db` puis `uv run pytest` |
| Lancer l'application (migrations comprises) | `docker compose up -d --build --wait app` → <http://127.0.0.1:8000/health> |
| Appliquer les migrations (base de développement) | `docker compose run --rm --build migrate` |
| Inviter une personne (création de compte) | `docker compose run --rm app rocky-admin invite <email>` |
| Arrêter | `docker compose down` (les données restent dans le volume `rocky-db-data`) |

La vérification globale n'a besoin que de Docker ; elle tourne contre une base PostgreSQL de test jetable
(`test-db`, publiée sur `127.0.0.1:55432`).

Il n'y a pas d'inscription publique : un compte naît par invitation. La personne invitée reçoit un lien
d'activation (valable 7 jours), choisit son mot de passe et reste connectée tant qu'elle revient au moins une fois
par semaine.

## Structure

```
rocky/
  system/        socle technique : configuration, base, comptes, événements, web…
  profil/        profil unique FR/EN, pistes, compétences, CV maître
  offres/        sources, analyse d'annonce, scoring, veille, décisions
  candidatures/  dossier, statuts, documents, envoi, suivi
  messages/      Gmail, classification, alertes emploi
tests/<module>/  tests du nouveau Rocky (les tests/test_*.py à plat sont ceux de l'ancien)
docs/            plan de refonte, décisions, procédures
```

Les autres dossiers à la racine (`dashboard/`, `database/`, `scripts/`…) appartiennent à l'ancien Rocky et seront
retirés à la bascule (étape F2).
