# A1 — Archive de l'ancien Rocky

Date : 24/09/2026 · Étape : A1 (plan v2) · Procédure : `docs/procedures/a1-archive/`

## Décisions (validées avec Nicolas)

| Sujet | Décision | Raison |
|---|---|---|
| Version de référence | Tag annoté `rocky-v1-streamlit` sur `7b5759a` (pointe de `nico-dev`) | Le code de l'image en service (`rocky-assistant:local`, construite le 23/09) est identique, fichier par fichier, aux commits `d7d9aa1`…`7b5759a`. `main` a divergé (78/82 fichiers) et ne correspond pas à ce qui tourne. |
| Branche | `refonte`, créée depuis le commit du plan v2 validé ; tag et branche poussés sur origin | Demande de Nicolas : tag avant la branche. |
| Emplacement | `backups/rocky-v1-<AAAAMMJJ>/` dans le dépôt, ignoré par `.gitignore` | Choix de Nicolas, à côté des dumps d'août. |
| Bases | Dump complet de `job_assistant` (base en service) **et** de `rocky` (ancienne base) ; exports Parquet/CSV pour `job_assistant` seulement | `rocky` est plus ancienne (790 offres, 100 mails) : conservée, pas analysée. |
| Source des exports | La **copie restaurée**, pas la base live | Les exports correspondent exactement au dump vérifié ; aucune charge sur l'ancien Rocky. |
| Secrets | Rôles exportés `--no-role-passwords` ; `user_sessions`, `account_tokens`, `users.password_hash` absents des exports (présents dans le dump) ; `*/gmail/` (jetons OAuth) et `*/browser_profile/` (cookies) non copiés ; `.env` jamais lu (accès par la socket du conteneur) | AGENTS.md §3. |
| Transport | Flux `docker exec … > fichier` / stdin, jamais de montage bind | Montages bind Docker instables sous macOS (`Resource deadlock avoided`, OSError 35). |

## Interprétation du critère de sortie

- **« Comptes identiques »** : table `users` identique ligne à ligne (id, e-mail, empreinte du mot de passe,
  statut…) et rôle PostgreSQL `job_user` aux mêmes attributs. Plus largement, les 20 tables des deux bases
  ont la même empreinte (nombre de lignes + md5 du contenu) avant dump, après dump et après restauration.
- **« Exports lisibles dans un notebook »** : `verification/lecture_exports.ipynb` exécuté par `nbconvert`,
  sans erreur ; nombres de lignes Parquet = CSV = manifeste pour les 18 tables exportées.

## Résultat (archive `backups/rocky-v1-20260924/`, 131 Mo, 434 fichiers)

- `restauration.txt` : OK pour `job_assistant` et `rocky`, comptes et rôles identiques.
- Exports : 1 249 offres, 474 scores + 527 historiques, 1 295 rattachements, 52 candidatures,
  48 documents, 116 événements, 53 veilles, 806 mails, profil complet (5 profils, 65 compétences, 8 projets).
- Documents : 168 références présentes sur 169. Seule absente : `data/profiles/2/cv.pdf`, CV du profil de test
  « Nico enseignant test_version », introuvable sur disque (fichier jamais conservé par l'ancien Rocky).
- Les chemins relatifs `output/candidatures/2026-08-…` se résolvent depuis `./output` de l'hôte
  (dont `output/previous_outputs/`), copié dans `documents/hote/output/`.
- `SHA256SUMS` vérifié ; aucun fichier secret dans l'archive ; conteneur de contrôle supprimé ;
  ancien Rocky toujours disponible (HTTP 200 sur `127.0.0.1:8501`).

## Synchronisation iCloud (résolu)

Pendant A1, le dépôt était sur le Bureau synchronisé par iCloud (fichiers « non téléchargés » constatés dans
`./output`), donc l'archive — données personnelles et empreintes de mots de passe — y partait aussi.
Le 24/09, après rapatriement complet des fichiers (aucun fichier « dataless » restant, `SHA256SUMS` de l'archive
vérifié), Nicolas a renommé le dépôt en `Rocky_assistant_job.nosync` : iCloud l'exclut désormais.
Nouveau chemin : `~/Desktop/Projets_IA/Rocky_assistant_job.nosync` ; l'archive reste dans `backups/`.
Attention : renommer en `.nosync` un dossier contenant des fichiers encore dataless les rend illisibles ;
toujours vérifier `find . -flags +dataless` avant.
