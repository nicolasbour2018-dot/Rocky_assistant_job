#!/usr/bin/env bash
# Archive complète de l'ancien Rocky (étape A1 du plan de refonte v2).
#
# Produit, dans un dossier jamais versionné :
#   db/          dumps pg_dump (format custom) des bases, rôles sans mot de passe, copies SQLite
#   exports/     Parquet + CSV des tables utiles à l'analyse, lus depuis la copie restaurée
#   documents/   documents du volume Docker, de ./output et de ./data, sans jetons OAuth ni profil navigateur
#   verification/ empreintes live et restaurées, rapport de restauration, rapport documents, notebook exécuté
#   SHA256SUMS   empreinte de chaque fichier de l'archive
#
# Lecture seule sur l'ancien Rocky : aucune écriture dans ses bases ni dans son volume.
# Les montages bind Docker étant instables sous macOS (OSError 35), tout transite par stdout/stdin.
#
# Usage : docs/procedures/a1-archive/archive.sh [dossier_cible]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
OUT="${1:-$ROOT/backups/rocky-v1-$(date +%Y%m%d)}"

LIVE_PG="${LIVE_PG:-job-assistant-postgres}"
APP="${APP:-rocky-assistant-local}"
PG_USER="${PG_USER:-job_user}"
DATABASES=(job_assistant rocky)
EXPORT_DB="job_assistant"
RESTORE="rocky-a1-restore"
RESTORE_PORT="${RESTORE_PORT:-55432}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
JUPYTER="${JUPYTER:-/opt/anaconda3/bin/jupyter}"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ÉCHEC : $*"; exit 1; }

if [[ -e "$OUT" ]] && [[ -n "$(ls -A "$OUT")" ]]; then
    die "$OUT existe déjà et n'est pas vide : une archive n'est jamais écrasée."
fi
docker inspect "$RESTORE" >/dev/null 2>&1 && die "le conteneur $RESTORE existe déjà (reste d'une exécution précédente ?)."
for c in "$LIVE_PG" "$APP"; do
    [[ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" == "true" ]] || die "conteneur $c absent ou arrêté."
done

mkdir -p "$OUT"/{db/sqlite,exports,documents/volume,documents/hote/data,documents/hote/output,verification}
OUT="$(cd "$OUT" && pwd)"
VERIF="$OUT/verification"

RESTORE_STARTED=0
cleanup() {
    if [[ "$RESTORE_STARTED" == 1 ]]; then
        docker rm -f "$RESTORE" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Empreinte de chaque table : nombre de lignes + md5 des md5 de lignes triés (indépendant de l'ordre physique).
# Les réglages de session fixent le rendu texte des dates et flottants, pour comparer deux serveurs.
fingerprint() {
    local container="$1" db="$2"
    docker exec -i "$container" psql -U "$PG_USER" -d "$db" -X -q -At -F'|' -v ON_ERROR_STOP=1 <<'SQL'
SET TimeZone = 'UTC';
SET DateStyle = 'ISO, MDY';
SET IntervalStyle = 'postgres';
SET extra_float_digits = 3;
SELECT format(
    'SELECT %L, count(*), coalesce(md5(string_agg(md5(x::text), %L ORDER BY md5(x::text))), %L) FROM %I.%I x',
    table_schema || '.' || table_name, '', 'vide', table_schema, table_name)
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name
\gexec
SQL
}

roles() {
    docker exec "$1" psql -U "$PG_USER" -d postgres -X -At -F'|' -v ON_ERROR_STOP=1 -c \
        "SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls
         FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY rolname"
}

# 1-3. Dumps encadrés par deux empreintes live identiques (sinon l'app a écrit pendant le dump : on recommence).
for db in "${DATABASES[@]}"; do
    for attempt in 1 2 3; do
        log "$db : empreinte live, dump (tentative $attempt)"
        fingerprint "$LIVE_PG" "$db" > "$VERIF/$db.live_avant.txt"
        docker exec "$LIVE_PG" pg_dump -U "$PG_USER" -Fc "$db" > "$OUT/db/$db.dump"
        fingerprint "$LIVE_PG" "$db" > "$VERIF/$db.live.txt"
        if cmp -s "$VERIF/$db.live_avant.txt" "$VERIF/$db.live.txt"; then
            rm "$VERIF/$db.live_avant.txt"
            break
        fi
        [[ "$attempt" == 3 ]] && die "$db a changé pendant les trois tentatives de dump."
        log "$db a changé pendant le dump, nouvelle tentative"
    done
done
log "rôles (sans mot de passe)"
docker exec "$LIVE_PG" pg_dumpall -U "$PG_USER" --globals-only --no-role-passwords > "$OUT/db/globals.sql"
roles "$LIVE_PG" > "$VERIF/roles.live.txt"
docker exec "$LIVE_PG" pg_dump --version > "$VERIF/pg_dump_version.txt"

# 4. Restauration sur une base vierge, dans un conteneur éphémère sans volume.
RESTORE_PASSWORD="$(openssl rand -hex 24)"
log "restauration de contrôle dans $RESTORE"
docker run -d --name "$RESTORE" -e POSTGRES_USER="$PG_USER" -e POSTGRES_PASSWORD="$RESTORE_PASSWORD" \
    -p "127.0.0.1:$RESTORE_PORT:5432" "$(docker inspect -f '{{.Config.Image}}' "$LIVE_PG")" >/dev/null
RESTORE_STARTED=1
for _ in $(seq 60); do
    # -h 127.0.0.1 : le serveur temporaire d'initialisation n'écoute que sur la socket Unix.
    docker exec "$RESTORE" pg_isready -q -h 127.0.0.1 -U "$PG_USER" -d postgres && break
    sleep 1
done
docker exec "$RESTORE" pg_isready -q -h 127.0.0.1 -U "$PG_USER" -d postgres || die "le PostgreSQL de restauration ne démarre pas."

# Le rôle job_user existe déjà (POSTGRES_USER) : seul « CREATE ROLE » échoue, les ALTER ROLE s'appliquent.
docker exec -i "$RESTORE" psql -U "$PG_USER" -d postgres -X -q < "$OUT/db/globals.sql" \
    > "$VERIF/globals_restauration.log" 2>&1 || true
for db in "${DATABASES[@]}"; do
    docker exec "$RESTORE" createdb -U "$PG_USER" "$db"
    docker exec -i "$RESTORE" pg_restore -U "$PG_USER" -d "$db" --exit-on-error < "$OUT/db/$db.dump"
    fingerprint "$RESTORE" "$db" > "$VERIF/$db.restauree.txt"
done
roles "$RESTORE" > "$VERIF/roles.restauree.txt"

# 5. Comparaison live ↔ restaurée.
REPORT="$VERIF/restauration.txt"
ok=1
{
    echo "Restauration de contrôle — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Source : conteneur $LIVE_PG ; cible : conteneur éphémère $RESTORE (base vierge)"
    echo
    for db in "${DATABASES[@]}"; do
        echo "== Base $db"
        if diff "$VERIF/$db.live.txt" "$VERIF/$db.restauree.txt"; then
            echo "Identique : $(wc -l < "$VERIF/$db.live.txt" | tr -d ' ') tables, lignes et contenus (empreinte md5)."
        else
            echo "DIFFÉRENCE"; ok=0
        fi
        echo "Comptes Rocky (table users) : $(grep '^public.users|' "$VERIF/$db.restauree.txt" | cut -d'|' -f2) ligne(s)"
        if [[ "$(grep '^public.users|' "$VERIF/$db.live.txt")" == "$(grep '^public.users|' "$VERIF/$db.restauree.txt")" ]]; then
            echo "Comptes identiques (id, e-mail, empreinte du mot de passe, statut…)."
        else
            echo "COMPTES DIFFÉRENTS"; ok=0
        fi
        echo
    done
    echo "== Rôles PostgreSQL"
    if diff "$VERIF/roles.live.txt" "$VERIF/roles.restauree.txt"; then
        echo "Identiques : $(cut -d'|' -f1 "$VERIF/roles.live.txt" | paste -sd, -)"
    else
        echo "DIFFÉRENCE"; ok=0
    fi
    echo
    [[ "$ok" == 1 ]] && echo "RÉSULTAT : OK" || echo "RÉSULTAT : ÉCHEC"
} > "$REPORT"
cat "$REPORT" >&2
[[ "$ok" == 1 ]] || die "la restauration ne reproduit pas la base live (voir $REPORT)."

# 6. Exports depuis la copie restaurée (aucune charge sur la base live).
log "exports Parquet et CSV de $EXPORT_DB"
export PGPASSWORD="$RESTORE_PASSWORD"
DSN="postgresql://$PG_USER@127.0.0.1:$RESTORE_PORT/$EXPORT_DB"
"$PYTHON" "$HERE/export_tables.py" --dsn "$DSN" --out "$OUT/exports"

# 7. Documents : volume Docker puis ./data de l'hôte, sans secrets.
log "documents du volume"
docker exec "$APP" tar -C /data -cf - \
    --exclude='gmail' --exclude='browser_profile' --exclude='.DS_Store' \
    users profiles output data \
    | tar -C "$OUT/documents/volume" -xf -
docker exec "$APP" sh -c 'cd /data && for f in rocky.db rocky.db-wal rocky.db-shm; do [ -f "$f" ] && echo "$f"; done' \
    | while read -r f; do docker exec "$APP" cat "/data/$f" > "$OUT/db/sqlite/volume_$f"; done
# Sur l'hôte, les fichiers iCloud non téléchargés sont rapatriés à la lecture : cette partie peut être lente.
# Les chemins relatifs « output/… » d'août se résolvent depuis la racine du dépôt (l'app tournait alors sur l'hôte).
if [[ -d "$ROOT/output" ]]; then
    log "documents de ./output (hôte)"
    tar -C "$ROOT/output" -cf - --exclude='.DS_Store' . | tar -C "$OUT/documents/hote/output" -xf -
fi
if [[ -d "$ROOT/data" ]]; then
    log "documents de ./data (hôte)"
    tar -C "$ROOT/data" -cf - \
        --exclude='gmail' --exclude='browser_profile' --exclude='.DS_Store' --exclude='rocky.db*' --exclude='logs' . \
        | tar -C "$OUT/documents/hote/data" -xf -
    for f in rocky.db rocky.db-wal rocky.db-shm; do
        [[ -f "$ROOT/data/$f" ]] && cp -p "$ROOT/data/$f" "$OUT/db/sqlite/hote_$f"
    done
fi
if find "$OUT/documents" \( -path '*gmail*' -o -path '*browser_profile*' -o -name '*token*' -o -name 'credentials*.json' \) | grep -q .; then
    die "un fichier secret a été copié dans documents/ : archive à vérifier."
fi
"$PYTHON" "$HERE/verifier_documents.py" --dsn "$DSN" --documents "$OUT/documents" > "$VERIF/documents.txt"
unset PGPASSWORD

# 8. Lecture des exports dans un notebook exécuté.
log "exécution du notebook de lecture"
cp "$HERE/lecture_exports.ipynb" "$VERIF/lecture_exports.ipynb"
"$JUPYTER" nbconvert --to notebook --execute --inplace "$VERIF/lecture_exports.ipynb" 2> "$VERIF/nbconvert.log"

cp "$HERE/README_archive.md" "$OUT/README.md"

# 9. Empreintes de l'archive.
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS)
log "archive terminée : $OUT ($(du -sh "$OUT" | cut -f1))"
