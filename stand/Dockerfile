FROM python:3.12-slim
WORKDIR /app
COPY stand/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY stand /app/stand
RUN pip install --no-deps . && useradd --uid 10001 --create-home researcher && mkdir /state /app/results && chown researcher /state /app/results
USER researcher
CMD ["python", "stand/run_e4.py", "--profile", "standard", "--output", "results/e4-local-standard.json"]
