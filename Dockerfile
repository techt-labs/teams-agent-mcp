# Standalone MCP layer image.
#
# Build context is the `server/` directory, because the package
# (`mcp_layer/`) imports itself absolutely. Build from there so it
# resolves:
#
#     docker build -t ea-mcp-layer .
#     docker run -p 8100:8100 --env-file mcp_layer/.env ea-mcp-layer
#
# Deploys unchanged on Azure App Service or Container Apps alongside the
# connector — two small services, one per concern. This one needs no
# public inbound from Teams; it is reached by the connector
# (CONNECTOR_INBOUND_URL -> /teams-inbound) and by the agent platform
# (the MCP tool surface). Keep it on the internal network if your
# topology allows.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_layer/ ./mcp_layer/

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8100

# One worker: the session store is the source of truth, so scale by
# running more stateless containers rather than more workers.
CMD ["uvicorn", "mcp_layer.app:app", "--host", "0.0.0.0", "--port", "8100"]
