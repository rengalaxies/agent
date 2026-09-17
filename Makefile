.PHONY: test pilot evaluation-check clean

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

pilot:
	PYTHONPATH=src python -m datamesh_release_protocol.cli run-catalog \
		--scenarios scenarios/development \
		--baseline policies/v1-ind.yaml \
		--output results/pilot-raw-results.json \
		--manifest results/run-manifest.json \
		--run-id development-pilot-0.3.1-dev3 \
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

evaluation-check:
	PYTHONPATH=src python -m unittest tests.test_evaluation_catalog -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -r {} +
	find . -type f -name '*.pyc' -delete
	rm -f results/pilot-raw-results.json results/pilot-results.json results/run-manifest.json results/pilot-score-manifest.json results/pilot-metrics.json
