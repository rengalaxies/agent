FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
ARG PRODUCT_SHA=WORKTREE
LABEL agent-graph-demo.product=$PRODUCT_SHA
WORKDIR /app
# Wheelhouse is prepared and hashed outside the VM. No network or trust-store modification in build.
COPY work/wheels /wheels
COPY infra/agent_graph_demo/requirements.lock /app/infra/agent_graph_demo/requirements.lock
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r infra/agent_graph_demo/requirements.lock && rm -rf /wheels
COPY src/agent_graph_demo /app/src/agent_graph_demo
# The demo imports the agent_graph core it ships (batch 2A). Batch 5A rebuilds this
# Dockerfile and removes core.lock.json and the separate /core mount.
COPY src/agent_graph /app/src/agent_graph
COPY constitutions/agent-service-v1.yaml /app/constitutions/agent-service-v1.yaml
COPY examples/agent_graph_demo /app/examples/agent_graph_demo
COPY tools/agent_graph_demo /app/tools/agent_graph_demo
COPY infra/agent_graph_demo/core.lock.json /app/infra/agent_graph_demo/core.lock.json
# The external pinned core is supplied as a separate read-only operator mount at /core.
RUN chmod -R a+rX /app
ENV PYTHONPATH=/app/src:/app PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
CMD ["python", "-m", "uvicorn", "agent_graph_demo.server:app", "--host", "0.0.0.0", "--port", "18081", "--workers", "1", "--no-access-log"]
