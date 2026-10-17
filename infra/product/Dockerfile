FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY infra/product/requirements.lock /app/requirements.lock
COPY src ./src
RUN pip install --no-cache-dir -c /app/requirements.lock '.[api]' && useradd --uid 10001 --create-home product
USER 10001:10001
EXPOSE 8081
ENTRYPOINT ["python", "-m", "change_completion.web_server"]
