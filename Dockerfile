# Managed Cloud.ru fallback: same research engine, UI and explicitly selected durable audit.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY services /app/services
COPY stand /app/stand
COPY policies /app/policies
COPY scenarios/development /app/scenarios/development
COPY ui/index.html /app/ui/index.html
RUN pip install --no-cache-dir '.[api,distributed,postgres]' && useradd --create-home --uid 1000 appuser && mkdir /audit-data && chown appuser:appuser /audit-data
ENV DMRP_REQUIRE_AUDIT=1
USER 1000
EXPOSE 8080
CMD ["uvicorn","services.managed_app:app","--host","0.0.0.0","--port","8080"]
