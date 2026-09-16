.PHONY: test pilot clean

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

pilot:
	PYTHONPATH=src python -m datamesh_release_protocol.cli run-catalog \
		--scenarios scenarios/development \
		--baseline policies/v1-ind.yaml \
		--oracle oracles/development.yaml \
		--output results/pilot-results.json \
		--manifest results/run-manifest.json \
		--metrics results/pilot-metrics.json

clean:
	find . -type d -name __pycache__ -prune -exec rm -r {} +
	find . -type f -name '*.pyc' -delete
	rm -f results/pilot-results.json results/run-manifest.json results/pilot-metrics.json
