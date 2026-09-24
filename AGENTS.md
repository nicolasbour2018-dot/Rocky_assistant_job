# Rocky — Règles pour les agents

## 1. Contexte

Rocky est en **refonte complète**. Le document normatif est `docs/rocky-refonte-plan-v2.md`.
Le nouveau Rocky est développé sur la branche de refonte, à côté de l'ancien (Streamlit),
qui reste l'outil quotidien de Nicolas jusqu'à la bascule (étape F2).

Ordre des sources de vérité, en cas de conflit :
1. `docs/rocky-refonte-plan-v2.md` (décisions D1–D16, étapes, critères de sortie) ;
2. ce fichier ;
3. `docs/decisions/` (décisions détaillées prises pendant une étape) ;
4. le code du nouveau Rocky.

`docs/archive/` et l'ancien code sont **historiques et non normatifs** : on peut les lire pour porter
une logique, jamais les suivre comme règle. Les règles `.claude/rules/` héritées de l'ancien Rocky
ne s'appliquent pas au nouveau code tant qu'elles n'ont pas été alignées sur le plan v2.

## 2. Méthode de travail

- Lire le plan v2 en entier, puis ne réaliser **qu'une seule étape** à la fois.
- Respecter le niveau de préparation de l'étape : direct, mode plan, ou *grill me* puis mode plan.
  Tout plan cite le critère de sortie de l'étape et liste les fichiers qu'il touche.
- Une étape est terminée quand son **critère de sortie est vérifié** et que la vérification globale est verte.
- Mettre à jour la colonne « État » de l'étape dans le plan.
- Un constat hors du périmètre de l'étape est **noté** dans la section 8 du plan (avec l'étape concernée), pas corrigé.
- Les décisions métier obtenues avec Nicolas sont consignées dans `docs/decisions/<étape>-<sujet>.md` avant l'implémentation.
- Une étape = une session de travail = un commit (ou une petite série de commits cohérente).
- En cas de doute sur une règle métier : demander à Nicolas plutôt qu'inventer.

## 3. Écritures

**Autorisé**
- Le nouveau code sous `rocky/` (`system/`, `profil/`, `offres/`, `candidatures/`, `messages/`).
- `tests/` pour le nouveau code.
- `docs/` : état des étapes et section 8 du plan, `docs/decisions/`, documentation du nouveau code.
- Les fichiers de racine prévus par le plan : `pyproject.toml`, `docker-compose.yml`, `.env.example`, `README`.
- L'ajout d'une dépendance quand l'étape le requiert, justifié dans le plan ou la décision de l'étape.

**Interdit**
- Modifier l'ancien Rocky : `dashboard/`, `database/`, `scripts/`, `cron/`, ancien `Dockerfile`,
  scripts Hugging Face (lecture autorisée ; retrait prévu uniquement en F2).
- Toucher la base de données utilisée au quotidien par l'ancien Rocky, ou l'archive (lecture seule).
- Lire, écrire ou versionner des secrets : `.env`, `credentials.json`, jetons OAuth, clés d'API.
- Créer des fichiers à la racine en dehors de ceux listés ci-dessus.
- Modifier les décisions D1–D16 du plan sans validation explicite de Nicolas.

## 4. Architecture (rappel du plan, section 3)

- Modules métier (`profil`, `offres`, `candidatures`, `messages`) sur un socle technique `system`.
  Un module utilise `system` ; il ne recopie pas ce qui s'y trouve et n'accède pas au SQL d'un autre module.
- Forme interne d'un module : règles métier (fonctions pures, dataclasses) → cas d'usage → accès SQL du module
  → routes FastAPI et gabarits HTMX.
- Les cas d'usage sont testables avec de faux adaptateurs, sans FastAPI, SQL, Gmail ni LLM.
- Pas d'interface par table, pas de hiérarchie de classes sans besoin démontré.
- Toute opération qui écrit plusieurs choses liées le fait **dans une seule transaction** et de façon **idempotente**.
- Toute décision ou transition est inscrite dans le journal d'événements (ajout seul).
- **Aucune exception avalée en silence** : une erreur est soit remontée, soit enregistrée et rendue visible.
- Une fonction de calcul (score, classification) n'a pas d'effet de bord ; l'écriture est une opération nommée séparée.
- PostgreSQL uniquement, y compris pour les tests (PostgreSQL de test). Schéma géré par Alembic.

## 5. Invariants produit

- Rocky **ne postule jamais** à la place de l'utilisateur : préremplissage avec confirmation, envoi final manuel.
- Gmail en **lecture seule** ; aucun élargissement de scope.
- Aucun contournement des protections des sites sources.
- Le scoring est **déterministe et explicable** ; le LLM n'attribue jamais le score.
- Le scoring stocke ses caractéristiques, preuves et version de règles ; les décisions de l'utilisateur
  sont conservées avec leur raison (données d'entraînement, décision D14).
- Aucune offre collectée n'est jetée : une offre sous le seuil est conservée avec son motif.

## 6. Réseau, API et données de test

- Tests : aucun appel réseau ni fournisseur LLM ; utiliser des jeux de données enregistrés et des faux adaptateurs.
- Appels réels (sources, Gmail, Groq) seulement quand l'étape l'exige, avec l'accord de Nicolas.
- Les jeux de test issus de l'archive sont anonymisés si nécessaire et ne contiennent aucun secret.

## 7. Vérification

<!-- À compléter à l'étape B1 -->
- Vérification globale : `…` (lint ruff, typage, tests)
- Tests seuls : `…`
- Lancer l'application : `…`

## 8. Standard de revue

Toute revue ou tout audit sépare :
1. les faits observés (avec références fichier/module) ;
2. les risques déduits ;
3. les recommandations, proportionnées au projet.

Le relecteur conteste toute affirmation non étayée par le dépôt.
