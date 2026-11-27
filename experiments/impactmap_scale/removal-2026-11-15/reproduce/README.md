# Recorded recipes

These scripts record the executed protocol; private inputs/Git mirrors are prerequisites. They do not fetch or reconstruct missing author data. Use a new private output root consistently; completed outputs are never overwritten.

For before-profile7 use source0582cd8, for after-profile9 source2d13227 in an appropriate checkout. Preserve the same private corpus pins and manifests. Copy run_removal_stages_final.py and removal_acceptance.py to the /tmp names used in these recipes, or change the helper paths consistently.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /tmp/run_removal_stages_final.py before-profile7
# On the final source, with identical private input manifests:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /tmp/run_removal_stages_final.py after-profile9
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /tmp/removal_acceptance.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.:work/batch06-quality/validator python -m tools.impactmap_eval.calibrate --corpus work/batch06/development-v2 --output NEW_AUTHOR_OUTPUT --post-tuning
```

Run stage timing sequentially without concurrent test/acceptance/quality jobs. Acceptance and quality may be parallel only after timing; their elapsed times are diagnostic, not performance comparisons. The campaign-controller script is the session orchestration record: it waits for the named verification log files, so do not run it without first creating those logs on the intended source. Report-builder helpers are provenance records and depend on the session templates/private paths; they are not a turnkey public-data generator.

Fresh verification of the saved portable report uses ../verify_artifacts.py. --private needs the original private inputs/oracles; --current-core needs exact tested source. Replacement diagnostic is authored and outside n40.
