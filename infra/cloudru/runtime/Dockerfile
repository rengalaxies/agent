FROM python@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi==0.115.12 uvicorn==0.34.2 httpx==0.28.1 pika==1.3.2 'psycopg[binary]==3.2.9'
WORKDIR /work
COPY . /work
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=/work
ENTRYPOINT ["python"]
