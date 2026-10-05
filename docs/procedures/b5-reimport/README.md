# B5 — Réimport du profil de Nicolas depuis l'archive A1

Décision : `docs/decisions/B5-profil-pistes.md` (Q10–Q13, Q17, Q19). À refaire tel quel à la bascule (F2), dans le
compte réel, avec le **même fichier relu**.

Le fichier de profil contient des données personnelles : il vit **hors du dépôt**
(`~/Developer/rocky-profil-nicolas.json`) et n'est jamais versionné. Le script refuse d'écrire dans le dépôt.

## 1. Extraire (Claude ou Nicolas)

```sh
python3 docs/procedures/b5-reimport/extract_profile.py \
  --archive backups/rocky-v1-20260924 --profile-id 1 --out ~/Developer/rocky-profil-nicolas.json
```

Le script lit uniquement les CSV de l'archive (`candidate_profiles`, `profile_localizations`, `candidate_skills`,
`profile_projects`, `profile_analyses`) et :
- normalise les niveaux (`Intermédiaire`, `intermédiaire` → `intermediate`) et les contrats (`CDI` → `permanent`) ;
- sort « Anglais (C1) » et « Espagnol (B2) » des compétences vers les langues, et ajoute le français (maternelle) ;
- applique les deux fusions de Q11 (le libellé perdant devient un alias) et signale tout autre doublon ;
- aligne les projets FR et EN par leur ordre, et lie les compétences citées qui existent dans le profil ;
- place dans `to_review` ce qui n'a pas de place évidente : intitulés et domaines de l'ancien profil, détails des
  projets, compétences de projet absentes du profil. L'adresse postale n'est pas reprise (Q23).

Mesuré le 25/09/2026 : 56 compétences → **52** (2 fusions, 2 langues), 3 langues, 4 projets.

Expériences et formations (Q19) : Claude a rédigé des brouillons à partir du CV FR de l'archive
(`documents/volume/users/1/profiles/1/fr/cv.pdf`). Le CV ne donne que des années : les mois sont provisoires
(janvier au début, décembre en fin) et signalés dans `to_review`.

## 2. Relire (Nicolas)

Ouvrir le fichier et, pour chaque ligne de `to_review` : la reporter là où elle doit aller (mot-clé de piste,
puce d'expérience…) ou l'abandonner. Corriger les mois, les compétences liées, les niveaux. **Vider ou retirer
`to_review`** : l'import refuse le fichier tant qu'elle contient quelque chose.

Format : `rocky-profil/1`, codes en anglais (voir la décision B5, « Codes stockés »). Une clé inconnue ou une valeur
invalide est refusée avec le chemin du champ (`skills[3].category : …`), toutes les erreurs d'un coup.

## 3. Importer (compte d'essai de la base de développement)

```sh
docker compose run --rm -v ~/Developer/rocky-profil-nicolas.json:/import/profil.json:ro \
  app rocky-admin import-profil /import/profil.json <adresse du compte d'essai>
```

L'import tient en une transaction : tout ou rien. Il refuse un profil qui a déjà un contenu, donc un second lancement
ne change rien (« rien n'a été importé »). Il écrit l'événement `profil.profile_imported`.

Les pistes ne sont pas dans le fichier : Nicolas les crée dans 👤 Profil & kit (Q15).

Répétition le 25/09/2026 dans un schéma jetable de `test-db` : 52 compétences, 0 libellé en double, 72 termes
uniques, 7 expériences et formations, 4 projets ; second lancement sans effet.
