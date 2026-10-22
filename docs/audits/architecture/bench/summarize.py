"""Markdown tables from results/phases.jsonl and results/cli.jsonl."""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

R = Path(__file__).resolve().parent / "results"
rows = [json.loads(line) for line in (R / "phases.jsonl").read_text().splitlines() if line.strip()]


def med(values):
    return st.median(values) if values else float("nan")


def ph(d, phase, key="wall"):
    return d["phases"].get(phase, {}).get(key, 0.0)


def each(d, phase, key):
    return d["phases"].get(phase, {}).get("each", {}).get(key, [])


print("## Synthetic scaling (deps=3, noise=4), median of reps\n")
print("| Файлов | МБ | Рёбер | Пробелов | prepare, холодный | из них обход 1 / 2 | извлечение | повторный prepare | dependencies | analyze_change | чтение контекста | контекст, МБ | SQLite после 3 контекстов, МБ | пик памяти, МБ | цитат в job |")
print("|" + "---|" * 15)
groups = defaultdict(list)
for d in rows:
    if d.get("corpus") == "synthetic" and d["deps"] == 3 and d["noise"] == 4:
        groups[d["n_files"]].append(d)
for n in sorted(groups):
    g = groups[n]
    c1 = med([each(d, "prepare_cold", "collect")[0] for d in g])
    c2 = med([each(d, "prepare_cold", "collect")[1] for d in g])
    print(f"| {g[0]['files']} | {g[0]['bytes']/1e6:.1f} | {g[0]['dependencies']} | {g[0]['gaps']} "
          f"| {med([ph(d,'prepare_cold') for d in g]):.2f} | {c1:.2f} / {c2:.2f} "
          f"| {med([ph(d,'prepare_cold','extract') for d in g]):.2f} | {med([ph(d,'prepare_warm') for d in g]):.2f} "
          f"| {med([ph(d,'dependencies') for d in g]):.2f} | {med([ph(d,'analyze_change') for d in g]):.2f} "
          f"| {med([ph(d,'store_get') for d in g]):.3f} | {g[0]['context_json_bytes']/1e6:.1f} "
          f"| {med([d['db_bytes'] for d in g])/1e6:.0f} | {med([d['peak_wset'] for d in g])/2**20:.0f} "
          f"| {g[0]['analysis']['citations']} |  (n={len(g)})")

print("\n## Density at 1000 files\n")
print("| deps/файл | noise/файл | Рёбер | Пробелов | prepare | извлечение | analyze_change | контекст, МБ | цитат |")
print("|---|---|---|---|---|---|---|---|---|")
for d in rows:
    if d.get("corpus") == "synthetic" and d["n_files"] == 1000 and d["rep"] == 1:
        print(f"| {d['deps']} | {d['noise']} | {d['dependencies']} | {d['gaps']} | {ph(d,'prepare_warm'):.2f} "
              f"| {ph(d,'prepare_warm','extract'):.2f} | {ph(d,'analyze_change'):.2f} "
              f"| {d['context_json_bytes']/1e6:.1f} | {d['analysis']['citations']} |")

print("\n## Real corpora\n")
print("| Корпус | Файлов | МБ | Операций | Рёбер | Пробелов | Коды пробелов | prepare, холодный | повторный prepare | извлечение | analyze_change | контекст, МБ | пик памяти, МБ |")
print("|" + "---|" * 13)
real = defaultdict(list)
for d in rows:
    if d.get("corpus") not in (None, "synthetic"):
        real[d["corpus"]].append(d)
for name, g in real.items():
    codes = ", ".join(f"{k} {v}" for k, v in sorted(g[0]["gap_codes"].items(), key=lambda kv: -kv[1]))
    print(f"| {name} | {g[0]['files']} | {g[0]['bytes']/1e6:.1f} | {g[0]['operations']} | {g[0]['dependencies']} | {g[0]['gaps']} | {codes} "
          f"| {med([ph(d,'prepare_cold') for d in g]):.2f} | {med([ph(d,'prepare_warm') for d in g]):.2f} "
          f"| {med([ph(d,'prepare_warm','extract') for d in g]):.2f} | {med([ph(d,'analyze_change') for d in g]):.2f} "
          f"| {g[0]['context_json_bytes']/1e6:.1f} | {med([d['peak_wset'] for d in g])/2**20:.0f} |  (n={len(g)})")

print("\nfirst_touch seconds:", {d.get("corpus") + str(d.get("n_files", "")): d.get("first_touch_seconds") for d in rows if d.get("rep") == 1})
print("import seconds median:", med([d["import_seconds"] for d in rows]))

cli = R / "cli.jsonl"
if cli.exists():
    print("\n## CLI job\n")
    for line in cli.read_text().splitlines():
        print(line)
