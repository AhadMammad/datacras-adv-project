#!/usr/bin/env bash
# Deploys every source-system model to its own PostgreSQL instance and checks it.
#   1. starts the 6 instances (docker compose)
#   2. (re)creates each database from 000_database.sql
#   3. applies ddl/010..090 with ON_ERROR_STOP
#   4. asserts table/column/FK counts against models/physical/manifest.json
#   5. runs the smoke test (one valid row per table, audit trigger, partition routing; rolled back)
# Usage: scripts/verify.sh [--keep]   (--keep leaves the containers running)
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP=${1:-}
MANIFEST=models/physical/manifest.json

docker compose up -d --wait >/dev/null 2>&1

psql_in() { # service db [psql args...]
  local svc=$1 db=$2; shift 2
  docker compose exec -T "$svc" psql -U postgres -d "$db" -v ON_ERROR_STOP=1 -q -X "$@"
}

fail=0
for db in $(python3 -c "import json;print(' '.join(json.load(open('$MANIFEST'))['systems']))"); do
  svc=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['systems']['$db']['service'])")
  dir=models/physical/$db/ddl
  echo "== $db on $svc"
  psql_in "$svc" postgres -c "DROP DATABASE IF EXISTS $db WITH (FORCE);"
  psql_in "$svc" postgres < "$dir/000_database.sql"
  for f in "$dir"/0[1-9]*.sql; do
    psql_in "$svc" "$db" < "$f" || { echo "FAILED: $f"; exit 1; }
  done

  expected=$(python3 -c "import json;m=json.load(open('$MANIFEST'))['systems']['$db'];print(m['tables'],m['columns'],m['foreign_keys'],m['ref_tables'])")
  actual=$(psql_in "$svc" "$db" -At -F' ' -c "
    WITH rels AS (
      SELECT c.oid, n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE c.relkind IN ('r','p') AND NOT c.relispartition
        AND n.nspname NOT IN ('pg_catalog','information_schema','audit','util'))
    SELECT
      (SELECT count(*) FROM rels WHERE nspname <> 'ref'),
      (SELECT count(*) FROM pg_attribute a JOIN rels r ON r.oid = a.attrelid
         WHERE a.attnum > 0 AND NOT a.attisdropped AND r.nspname <> 'ref'),
      (SELECT count(*) FROM pg_constraint k JOIN rels r ON r.oid = k.conrelid
         WHERE k.contype = 'f' AND k.conparentid = 0),
      (SELECT count(*) FROM rels WHERE nspname = 'ref');")
  if [[ "$expected" == "$actual" ]]; then
    echo "   counts ok (tables columns fks ref_tables): $actual"
  else
    echo "   COUNT MISMATCH expected [$expected] actual [$actual]"; fail=1
  fi

  if psql_in "$svc" "$db" < "tests/smoke/$db.sql"; then
    echo "   smoke ok"
  else
    echo "   SMOKE FAILED"; fail=1
  fi
done

#[[ "$KEEP" == "--keep" ]] || docker compose down >/dev/null 2>&1
exit $fail
