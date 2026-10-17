.PHONY: test pilot business-pilot evaluation-check clean

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

pilot:
	PYTHONPATH=src python -m datamesh_release_protocol.cli run-catalog \
		--scenarios scenarios/development \
		--baseline policies/v1-ind.yaml \
		--output results/pilot-raw-results.json \
		--manifest results/run-manifest.json \
		--run-id development-pilot-0.3.1-dev4 \
		--purpose development_regression
	PYTHONPATH=src python -m datamesh_release_protocol.cli score-results \
		--raw-results results/pilot-raw-results.json \
		--run-manifest results/run-manifest.json \
		--scenarios scenarios/development \
		--catalog-manifest experiments/development-catalog.yaml \
		--analysis-plan experiments/analysis-plan-0.3.1.yaml \
		--oracle oracles/development.yaml \
		--output results/pilot-results.json \
		--metrics results/pilot-metrics.json \
		--score-manifest results/pilot-score-manifest.json

business-pilot:
	PYTHONPATH=src python -m datamesh_release_protocol.cli business-case \
		--scored-results results/pilot-results.json \
		--metrics results/pilot-metrics.json \
		--model business/economic-model.yaml \
		--output results/business-case-development.json

evaluation-check:
	PYTHONPATH=src python -m unittest tests.test_evaluation_catalog -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -r {} +
	find . -type f -name '*.pyc' -delete
	rm -f results/pilot-raw-results.json results/pilot-results.json results/run-manifest.json results/pilot-score-manifest.json results/pilot-metrics.json
	rm -f results/business-case-development.json

.PHONY: e4-fast e4-standard e4-recovery
e4-fast:
	PYTHONPATH=src python stand/run_e4.py --profile fast --output results/e4-local-fast.json

e4-standard:
	PYTHONPATH=src python stand/run_e4.py --profile standard --output results/e4-local-standard.json

e4-recovery:
	PYTHONPATH=src python stand/recovery_check.py
