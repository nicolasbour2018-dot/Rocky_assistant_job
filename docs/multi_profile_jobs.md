# Rocky — rattachement des annonces aux profils

## Diagnostic initial

Rocky possédait déjà une table centrale `job_offers`, une table
`candidate_profiles` avec un unique profil actif et des scores dans
`job_matches(job_id, profile_id)`. La requête `fetch_jobs(profile_id)` utilisait
bien le score du profil demandé, mais retournait toutes les annonces à cause de
son `LEFT JOIN` sans filtre.

`job_matches` ne pouvait pas servir de relation générale : son score est
obligatoire, alors qu'une annonce incomplète doit être rattachée à un profil
sans être matchée. Les doublons rencontrés par un second profil n'étaient pas
non plus rattachés à celui-ci.

## Solution retenue

Une table de liaison minimale a été ajoutée :

```text
candidate_profiles
        │
        ├── profile_jobs ── job_offers
        │
        └── job_matches ─── job_offers
```

- `profile_jobs` signifie uniquement « cette annonce appartient au flux de ce
  profil ».
- `job_matches` conserve le score et son détail propres au profil.
- `job_offers` reste l'unique source des informations de l'annonce.
- La clé primaire `(profile_id, job_id)` rend le rattachement idempotent.

Le chemin principal est :

```text
candidate_profiles.is_active
  → RockyRepository.fetch_active_profile()
  → RockyRepository.get_jobs_for_profile(profile.id)
  → dashboard_common.load_data()
  → dashboard_b.py
```

Le cockpit n'a donc pas été dupliqué et ne connaît pas la table de liaison.

## Écriture pendant une veille

La veille connaît déjà le profil actif. Lorsqu'une annonce est :

- nouvelle et complète : elle est insérée, rattachée puis matchée ;
- nouvelle et incomplète : elle est insérée et rattachée sans matching ;
- déjà connue : elle n'est pas dupliquée, mais le nouveau rattachement est
  ajouté ; si elle est complète et n'a jamais été matchée pour ce profil, son
  score propre à ce profil est calculé une seule fois.

Les imports URL, recalculs de matching et créations de candidatures garantissent
également le rattachement via le repository.

## Migration des données historiques

La migration est intégrée aux deux schémas idempotents déjà exécutés au
démarrage de Rocky : `database/schema.sql` et `database/schema_sqlite.sql`.
Elle ne modifie ni ne supprime aucune ligne de `job_offers`.

L'ordre de reprise est :

1. relations certaines trouvées dans `job_matches` ;
2. relations certaines trouvées dans `applications` ;
3. annonces créées entre le début et la fin d'un `watch_run`, rattachées au
   profil de cette veille ;
4. annonces anciennes restant sans aucune trace, rattachées au profil le plus
   ancien pour préserver le comportement historique mono-profil.

Tous les `INSERT` ignorent un couple déjà présent. Le schéma peut donc être
rejoué sans créer de doublon.

## Retour en arrière

Le rollback fonctionnel le plus sûr consiste à remettre `fetch_jobs` dans son
comportement global sans supprimer la table `profile_jobs`. Les données
centrales n'auront jamais été déplacées.

Si la table doit réellement être retirée après sauvegarde :

```sql
DROP TABLE profile_jobs;
```

Cette suppression enlève uniquement les rattachements. Elle ne supprime ni les
annonces, ni les profils, ni les matchings, ni les candidatures. Elle n'est pas
automatique car Rocky recréerait la table au prochain démarrage tant que les
schémas contiennent cette évolution.

## Limite volontaire

Le statut utilisateur demeure actuellement porté par `job_offers`. Une annonce
partagée conserve donc le même statut visible pour tous ses profils. Déplacer
un jour ce statut dans `profile_jobs` serait une évolution possible si les
usages montrent que chaque profil doit avoir son propre cycle de candidature ;
ce changement n'est pas nécessaire au filtrage demandé et n'est pas inclus ici.
