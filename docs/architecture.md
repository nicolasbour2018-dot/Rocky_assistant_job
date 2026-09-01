# Architecture cible de Rocky

Ce document dessine la cible décidée dans les ADR 0005 à 0013
(`docs/decisions/`). Le code actuel, dans `dashboard/`, ne la suit pas
encore : la migration se fait fonctionnalité par fonctionnalité (ADR 0013).

## Comment lire ces schémas

Les schémas sont écrits en Mermaid, un texte que beaucoup d'outils savent
dessiner :

- Sur GitHub, ouvrir ce fichier : les schémas s'affichent directement.
- Dans VS Code, ouvrir l'aperçu Markdown (`Cmd+Shift+V`) avec l'extension
  « Markdown Preview Mermaid Support ».
- Avec Claude Code, demander « publie docs/architecture.md en artifact » :
  la page web rend les schémas.
- Avec Codex ou tout autre agent, demander « explique-moi le schéma des
  couches dans docs/architecture.md » : le schéma est du texte, l'agent le
  lit tel quel.
- Pour retoucher un schéma sans rien installer, coller son bloc sur
  https://mermaid.live.

## 1. Vue d'ensemble : qui parle à quoi

Tout tourne sur le Mac de Nicolas (ADR 0005). Deux points d'entrée : le
navigateur et `launchd`.

```mermaid
flowchart LR
    N["Nicolas"] -->|"navigateur, localhost"| WEB["rocky serve<br/>FastAPI + htmx"]
    L["launchd<br/>midi, ou au réveil"] -->|"rocky daily"| CLI["CLI rocky"]
    WEB --> APP["Cas d'usage"]
    CLI --> APP
    APP --> DB[("SQLite<br/>rocky.db")]
    APP --> M["API Mistral"]
    APP --> G["Gmail<br/>lecture seule"]
    APP --> S["Sources d'offres<br/>France Travail, Apec, Adzuna,<br/>WTTJ, TheirStack, LinkedIn, Wellfound"]
    APP --> T["typst<br/>PDF des lettres et CV"]
    APP --> B["Chromium via Playwright<br/>préremplissage supervisé"]
```

## 2. Les couches et le sens des dépendances

C'est le schéma à connaître par coeur (ADR 0008). Les flèches pleines sont
des imports autorisés. Toute flèche dans l'autre sens est une erreur, et
`lint-imports` la refuse.

```mermaid
flowchart TB
    subgraph ENTREE["Entrées : ce qui déclenche et assemble"]
        WEB["web/<br/>FastAPI, Jinja2, htmx"]
        CLI["cli/<br/>typer"]
    end
    subgraph APP["application/ : les cas d'usage"]
        UC1["Veille quotidienne"]
        UC2["Triage Gmail"]
        UC3["Préparer une candidature"]
        UC4["Générer un document"]
    end
    subgraph AD["adapters/ : le monde extérieur"]
        ADB["db/<br/>SQLAlchemy, Alembic"]
        AMI["mistral/"]
        AGM["gmail/"]
        ASO["sources/"]
        ADO["documents/<br/>typst"]
        ABR["browser/<br/>Playwright"]
    end
    subgraph DOM["domain/ : le coeur, sans dépendance externe"]
        E["Entités<br/>JobOffer, CandidateProfile, Application"]
        R["Règles<br/>matching : score déterministe"]
        P["Ports, des Protocol<br/>JobRepository, JobSource, LlmGateway,<br/>MailReader, DocumentRenderer"]
    end
    WEB --> APP
    CLI --> APP
    WEB -->|"composition : choisit les adaptateurs"| AD
    CLI -->|"composition"| AD
    APP --> DOM
    AD -->|"implémentent les ports"| P
```

Les cinq règles, dans l'ordre d'importance :

1. `domain/` n'importe rien d'externe : ni SQLAlchemy, ni FastAPI, ni httpx,
   ni le SDK Mistral.
2. `application/` ne connaît que `domain/`. Il reçoit les adaptateurs par
   injection, sous la forme des ports.
3. `adapters/` implémentent les ports et ne s'importent jamais entre eux.
4. `web/` et `cli/` sont les seuls endroits qui assemblent le tout.
5. Avant de commiter : `lint-imports`, `ruff check`, `pytest`.

## 3. Un parcours complet : préparer une candidature

Le même chemin vaut pour tous les cas d'usage : la route ne fait que
traduire la requête, le cas d'usage orchestre, les ports isolent le monde
extérieur.

```mermaid
sequenceDiagram
    actor N as Nicolas
    participant W as web/ route htmx
    participant A as application/ PrepareApplication
    participant R as port JobRepository
    participant L as port LlmGateway
    participant D as port DocumentRenderer
    N->>W: clic « Préparer » (requête htmx)
    W->>A: execute(user, job_id, profile_id)
    A->>R: offre et profil
    R-->>A: JobOffer, CandidateProfile
    A->>L: lettre adaptée, réponse attendue en modèle pydantic
    L-->>A: LetterDraft validé
    A->>D: rendre le PDF
    D-->>A: chemin du PDF
    A->>R: enregistrer la candidature et le document
    A-->>W: ApplicationPrepared
    W-->>N: fragment HTML mis à jour, sans rechargement
    Note over R,D: implémentés par adapters/db, adapters/mistral, adapters/documents
```

## 4. Le cycle quotidien

`launchd` lance `rocky daily` à midi, ou au réveil si l'heure est passée
pendant le sommeil du portable (ADR 0012). Le verrou empêche deux
exécutions en même temps.

```mermaid
flowchart TB
    L["launchd<br/>12:00, ou au réveil"] --> C["rocky daily"]
    C --> K{"verrou flock<br/>déjà pris ?"}
    K -- "oui" --> Z["ne rien faire, code 0"]
    K -- "non" --> G["Triage Gmail<br/>règles déterministes, lecture seule"]
    G --> W["Veille : chaque source, chaque profil"]
    W --> S["Score déterministe<br/>matching"]
    S --> DB[("SQLite")]
    G --> DB
    DB --> R["Rapport de run<br/>SUCCESS, PARTIAL, FAILED"]
```

## 5. La transition depuis Streamlit

Pendant la migration, les deux applications tournent côte à côte sur deux
ports de `localhost`. Le cookie de session ignore le port : la même table
`user_sessions` sert aux deux (ADR 0006). Chaque lot migre une
fonctionnalité en entier et supprime la page Streamlit correspondante.

```mermaid
flowchart LR
    N["Navigateur<br/>cookie rocky_session"] --> ST
    N --> FA
    subgraph MAC["Le Mac de Nicolas"]
        ST["Streamlit :8501<br/>pages restantes"]
        FA["FastAPI :8000<br/>pages migrées"]
        DB[("rocky.db<br/>table user_sessions partagée")]
    end
    ST --> DB
    FA --> DB
```

## 6. Où va le code actuel

| Aujourd'hui | Cible |
|---|---|
| `dashboard/rocky/matching.py`, `language.py`, règles de `gmail_service.py` | `domain/` |
| `dashboard/rocky/models.py` (dataclasses) | `domain/` entités |
| `dashboard/rocky/repository.py`, SQL de `auth.py` | `adapters/db/` |
| `dashboard/rocky/auth.py` (hachage, sessions, verrouillage) | `domain/` et `application/`, conservé |
| `dashboard/rocky/llm.py` | `adapters/mistral/` et cas d'usage dans `application/` |
| `dashboard/rocky/gmail_service.py` (lecture) | `adapters/gmail/` |
| `dashboard/rocky/sources/` | `adapters/sources/` |
| `letters.py`, `profile_documents.py`, `cv_tailoring.py` | `adapters/documents/` (typst) et `application/` |
| `browser_apply.py`, `scripts/prefill_application.py` | `adapters/browser/` |
| `dashboard/page_*.py`, `dashboard_v2.py` | `web/` routes et templates |
| `scripts/*.py` | `cli/` |
| `scheduler.py`, `cron/` | deux plists `launchd` |
