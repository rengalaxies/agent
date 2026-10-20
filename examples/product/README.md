# Product contract examples

These JSON files describe transitions; JSON is only the manifest serialization, not a required application transport. The component profiles can describe services, events, batch files, databases, reports or other supported artifacts.

- `service-event.json`: service/event change with a Java consumer.
- `batch-report.json`: batch/report change with two consumers and deliberately different 90d/30d requirements.

These are synthetic declarations, not runnable migrations. `fixture://` references and digests are illustrative placeholders; no source retrieval, artifact integrity verification or qualified adapter implementation is supplied here. Missing capabilities, grants and declared unknowns produce blockers. Profiles are exact identifiers, not a claim of generic Java, Kafka, CSV or SQL support; their version/construct definitions and qualification must be supplied with real adapters.

Run the boundary tests from the repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests/product -v
```

The common contracts are in `src/change_completion`. `assess_declarations` is pure and performs no I/O. It checks declared coverage of the listed `needs`, not completeness of the entire transition. Even `declared_coverage` is always `NOT_EXECUTED` and never authorizes effects. Deployment must independently validate the issuer/current status of grants, actual installed adapters and artifact integrity. Evidence context construction, execution, verification, persistent history and publication are later packages.
