# rocky-architecture-audit-v1-2026-09-23

## Objectif
Réaliser un audit architectural complet du projet Rocky afin d'évaluer son architecture actuelle, ses dépendances, ses flux de données, sa séparation des responsabilités, sa maintenabilité, sa testabilité, sa robustesse et sa capacité d'évolution.

L'audit doit s'appuyer uniquement sur le contenu réellement présent dans le dépôt. Il ne doit pas supposer l'existence de composants absents du code.

Le livrable final doit être écrit dans `docs/rocky-architecture-audit.md`.

## Critères d’acceptation
- Décrire l'architecture réellement observée dans le dépôt, avec les principaux composants, responsabilités, dépendances et flux de données.
- Identifier les points forts de l'architecture actuelle sans surévaluer leur maturité.
- Identifier les risques architecturaux, dettes techniques, couplages, responsabilités mal séparées, dépendances fragiles et zones difficiles à tester ou à faire évoluer.
- Examiner explicitement les couches ou fonctions liées à l'interface Streamlit, à la persistance PostgreSQL, à la collecte ou ingestion des offres, au matching, aux appels LLM, à la planification ou exécution périodique et à la configuration, lorsqu'elles existent réellement dans le dépôt.
- Distinguer clairement les constats factuels, les risques déduits et les recommandations.
- Pour chaque recommandation importante, expliquer le problème visé, le bénéfice attendu, le coût ou niveau d'effort approximatif et les risques de migration.
- Fournir un plan d'action priorisé en distinguant au minimum les corrections immédiates, les améliorations à moyen terme et les évolutions optionnelles.
- Éviter toute modification fonctionnelle du code source : seule la création ou mise à jour du rapport `docs/rocky-architecture-audit.md` est autorisée.
- Le rapport final doit contenir les sections exigées par la commande de validation configurée dans `project.yaml`.
- Le general_reviewer doit vérifier que les conclusions importantes du rapport sont traçables vers des fichiers, modules ou comportements réellement observés dans le dépôt.

## Contraintes
Ne modifier aucun fichier applicatif, test, configuration de production ou dépendance.

La seule écriture autorisée est `docs/rocky-architecture-audit.md`.

Ne pas lancer d'appel réseau externe ni de provider IA applicatif pour comprendre Rocky.

Ne pas tenter de corriger les problèmes découverts pendant cette mission.

Ne pas refactorer.

Ne pas créer de nouvelle architecture cible complète avant d'avoir décrit l'architecture existante.

Les recommandations doivent rester proportionnées à un projet personnel en évolution vers un outil réellement exploitable, sans proposer inutilement une architecture d'entreprise complexe.

## Contexte
Rocky est un assistant orienté recherche d'emploi et analyse d'offres. Le projet a évolué rapidement et a intégré plusieurs sources d'offres, une interface Streamlit, une base PostgreSQL, des traitements de matching et des fonctions liées aux LLM.

Cette mission sert aussi de test réel du harnais `agent_system` V3. L'objectif est donc de vérifier que l'orchestrateur délègue correctement l'analyse, que l'architecte produit des constats utiles, que le writer ne modifie que le livrable autorisé et que le reviewer contrôle la qualité du résultat.

## Références
- `AGENTS.md`
- `project.yaml`
- `harness.yaml`
- README et documentation présente dans le dépôt
- Code source, tests et fichiers de configuration réellement présents dans Rocky
