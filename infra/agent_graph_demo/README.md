# HTTP graph demo packaging

See [RUNBOOK](../../docs/agent-graph-demo/RUNBOOK.md). No VM actions are performed by these files.

- Dedicated hash-locked Python runtime; wheelhouse prepared outside target VM. Docker build uses `--network=none` and pinned Python base digest.
- Image contains the demo and the core of the same commit (`src/agent_graph`, `constitutions/agent-service-v1.yaml`). The separate core checkout and core.lock.json are gone since batch 5A; GraphCLI compares `agent_graph.core_identity()` of its subprocess with the imported core. No model policy/key is included.
- This is the old HTTP graph demo. The product installation is `infra/agent_service` (one installer, `box`).
- Web bind 127.0.0.1:18081; state separate from images; runtime registry read-only in web. One installation workload lock, one graph worker and one sandbox globally.
- Operator runtime plans are generated from fixed trusted release bytes with no user-selected commands, files, addresses or Compose projects. No host ports for services. Root-owned runtime registry remains separate from web-owned SQLite observations.
- Memory caps are configured bounds, not proof of target-VM fit. No image building or cloud changes on the shared VM.

`images.json` records base image and release convention; the actual application image ID/digest is in each ACCEPTANCE.json and deployment release.env. Do not replace it with a floating tag.
