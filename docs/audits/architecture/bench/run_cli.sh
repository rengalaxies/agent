#!/usr/bin/env bash
# CLI (subprocess) cost of one worker analyze_change job at several corpus sizes.
set -euo pipefail
B="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
cd "$B"
out=results/cli.jsonl
: > "$out"
for n in 10 100 1000; do
  d="runs/cli_$n"
  rm -rf "$d"
  "$PY" gen_corpus.py "$d" "$n" 3 4
  find "$d/repos" -type f -exec cat {} + > /dev/null   # first-open cost outside the measurement
  "$PY" bench_cli.py "$d" "[\"$d\",\"$n\",\"3\",\"4\"]" 20 \
    | "$PY" -c "import json,sys; d=json.load(sys.stdin); d.update(n_files=$n); print(json.dumps(d))" >> "$out"
  rm -rf "$d"
done
echo done
