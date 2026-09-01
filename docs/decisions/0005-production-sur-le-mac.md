# 0005 – Cible de production : le Mac de Nicolas

Date : 2026-09-01. Statut : acceptée.

## Contexte

Le Space Hugging Face est en `sdk: static` et ne fait pas tourner Rocky. Le
Dockerfile attend un compte PRO payant. Rocky est un projet personnel sans
budget d'hébergement, et Nicolas l'utilise depuis son propre ordinateur.

## Décision

La production est le poste de Nicolas. Cible de build : macOS sur Apple
Silicon, référence MacBook Air M1. La stack est entièrement gratuite et open
source ; seule l'API Mistral, déjà choisie, reste payante à l'usage.

Aucun serveur, aucun conteneur, aucun reverse proxy en chemin critique. Le
trafic reste sur `localhost`. Le modèle garde ses comptes utilisateurs, mais
un seul utilisateur réel est attendu.

## Conséquences

- SQLite devient la seule base (0007) ; `launchd` remplace cron (0012) ; le
  déploiement Hugging Face et le Dockerfile sont supprimés (0012).
- Le portable dort : l'ordonnanceur doit rattraper une exécution manquée.
- Toute dépendance doit publier une roue macOS arm64, ou se compiler avec les
  outils de base de Xcode.
- Sauvegarde = copie du dossier de stockage. Aucun chiffrement supplémentaire :
  le disque du Mac est déjà chiffré par FileVault quand il est activé, à
  vérifier avec Nicolas.
