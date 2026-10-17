ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm
FROM ${PYTHON_IMAGE}
WORKDIR /work
COPY lab/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY lab/app /work/lab/app
COPY lab/sql /work/lab/sql
COPY lab/contracts /work/lab/contracts
COPY lab/runtime /work/lab/runtime
COPY lab/product /work/lab/product
COPY lab/catalog /work/lab/catalog
COPY lab/evaluator /work/lab/evaluator
COPY lab/tests /work/lab/tests
COPY lab/reports/agent-ci-39066354050 /work/lab/reports/agent-ci-39066354050
RUN useradd --uid 10001 --create-home lab
USER 10001
ENTRYPOINT ["python", "-m", "lab.app.cli"]
