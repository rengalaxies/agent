# HTTP graph demo packaging

See [RUNBOOK](../../docs/agent-graph-demo/RUNBOOK.md). No VM actions are performed by these files.

- Dedicated hash-locked Python runtime; wheelhouse prepared outside target VM. Docker build uses `--network=none` and pinned Python base digest.
- Image contains demo wrapper/services/tools only. Accepted core a9385c5 is a **separate read-only mount**, verified against core.lock.json. No model policy/key is included.
- Web bind 127.0.0.1:18081; state separate from images; runtime registry read-only in web. One installation workload lock, one graph worker and one sandbox globally.
- Operator runtime plans are generated from fixed trusted release bytes with no user-selected commands, files, addresses or Compose projects. No host ports for services. Root-owned runtime registry remains separate from web-owned SQLite observations.
- Memory caps are configured bounds, not proof of target-VM fit. No image building or cloud changes on the shared VM.

`images.json` records base image and release convention; the actual application image ID/digest is in each ACCEPTANCE.json and deployment release.env. Do not replace it with a floating tag.
