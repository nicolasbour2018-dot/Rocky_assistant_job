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

## Résultat

Archive finale : `~/Developer/Rocky_assistant_job/backups/rocky-v1-20260924/` (77 Mo, 274 fichiers),
régénérée le 24/09 à 17:53 après l'incident iCloud ci-dessous.

- `restauration.txt` : OK pour `job_assistant` et `rocky`, comptes et rôles identiques.
- Exports : 1 278 offres, 477 scores + 534 historiques, 1 325 rattachements, 52 candidatures, 48 documents,
  116 événements, 54 veilles, 841 mails, profil complet (5 profils, 65 compétences, 8 projets).
- Documents : 168 références présentes sur 169. Seule absente : `data/profiles/2/cv.pdf`, CV du profil de test
  « Nico enseignant test_version », introuvable sur disque (fichier jamais conservé par l'ancien Rocky).
- Les chemins relatifs `output/candidatures/2026-08-…` se résolvent depuis le `output/` d'hôte de l'ancien Rocky,
  désormais dans son worktree `../Rocky_v1/output` (restauré depuis `~/Desktop/Projets_IA/Rocky_assistant_job_archive/output`,
  qui couvre les 72 chemins), copié dans `documents/hote/output/`.
- L'ancienne copie `./data` de l'hôte (doublon du volume Docker, dont un vieux `rocky.db`) a été perdue ; le volume
  reste la source et est archivé dans `documents/volume/` et `db/sqlite/volume_*`.
- `SHA256SUMS` vérifié ; notebook exécuté sans erreur ; aucun fichier secret dans l'archive ; conteneur de contrôle supprimé.

## Incident iCloud

Le dépôt était sur le Bureau, synchronisé par iCloud avec « Optimiser le stockage du Mac ». Des fichiers ont été
déchargés, puis les renommages en `.nosync` et le déplacement vers `~/Documents` (également synchronisé) ont abouti à la
**suppression locale** de la majeure partie du dépôt, dont `.git` et l'archive, sans passage par la Corbeille.
Le suffixe `.nosync` et « Garder téléchargé » n'ont pas protégé le dossier.

Rétablissement (24/09, avec l'accord exceptionnel de Nicolas pour manipuler `.env`, `.secrets` et `backups/`) :
- clone neuf de GitHub (branche `refonte`, `60323bd`) dans `~/Developer/`, hors iCloud ;
- `.env` récupéré de l'ancien dossier (clés identiques à celles du conteneur en service) ; `.secrets/` restauré depuis
  le volume Docker `rocky-assistant-secrets` ;
- archive régénérée par `archive.sh` depuis Docker (base et volume intacts, hors iCloud).

Pertes définitives côté Git : la branche locale `backup/nico-before-cleanup-20260826` et un `stash` sur
`codex/yolo-local-v2`, jamais poussés. Règle retenue : le dépôt ne vit jamais dans un dossier synchronisé.
