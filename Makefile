.PHONY: test pilot clean

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

pilot:
	PYTHONPATH=src python -m datamesh_release_protocol.cli run-catalog \
		--scenarios scenarios/development \
		--output results/pilot-results.json \
		--manifest results/run-manifest.json

clean:
	find . -type d -name __pycache__ -prune -exec rm -r {} +
	find . -type f -name '*.pyc' -delete
	rm -f results/pilot-results.json results/run-manifest.json
