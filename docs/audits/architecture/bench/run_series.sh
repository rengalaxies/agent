#!/usr/bin/env bash
# Scaling series. Each point: fresh corpus, fresh state, fresh process.
set -euo pipefail
B="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
cd "$B"
out=results/phases.jsonl
mkdir -p results
[ "${APPEND:-0}" = 1 ] || : > "$out"
point() { # files deps noise rep
  local d="runs/p_$1_$2_$3_$4"
  rm -rf "$d"
  "$PY" gen_corpus.py "$d" "$1" "$2" "$3"
  "$PY" bench_phases.py "$d/policy.json" "$d/state" "[\"$d\",\"$1\",\"$2\",\"$3\"]" \
    | "$PY" -c "import json,sys; d=json.load(sys.stdin); d.update(corpus='synthetic', n_files=$1, deps=$2, noise=$3, rep=$4); print(json.dumps(d))" >> "$out"
  rm -rf "$d"
}
real() { # name service edit-path rep
  local d="runs/r_$1_$4"
  rm -rf "$d"; mkdir -p "$d/repos"
  cp -r "corpora/$1" "$d/repos/$1"; rm -rf "$d/repos/$1/.git"
  cat > "$d/policy.json" <<EOF
{"installation_id":"bench","environment":"bench","subject":"bench",
 "capabilities":["read_context","maintain","propose","correct","report_check"],
 "repositories":[{"id":"$1","service":"$2","root":"repos/$1","revision":"pinned"}],
 "addresses":[{"service":"$2","base_url":"http://$1.internal:8000"}],
 "limits":{"max_files":10000,"max_file_bytes":262144,"max_corpus_bytes":20000000,"scan_seconds":120}}
EOF
  "$PY" bench_phases.py "$d/policy.json" "$d/state" "\"$d/repos/$1/$3\"" \
    | "$PY" -c "import json,sys; d=json.load(sys.stdin); d.update(corpus='$1', rep=$4); print(json.dumps(d))" >> "$out"
  rm -rf "$d"
}
if [ "${ONLY_TAIL:-0}" != 1 ]; then
for rep in 1 2 3; do
  for n in 10 100 1000 3000 9000; do point "$n" 3 4 "$rep"; done
done
for deps in 0 1 10 30; do point 1000 "$deps" 4 1; done
fi
for noise in 0 20; do point 1000 3 "$noise" 1; done
for rep in 1 2; do
  real requests Requests src/requests/api.py "$rep"
  real fastapi FastAPI fastapi/routing.py "$rep"
  real django Django django/db/models/query.py "$rep"
done
echo done
