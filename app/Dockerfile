# Image for the brain MCP service, the index/ingest Cloud Run Jobs, and the OAuth
# Authorization Server (same code, different entrypoint: each overrides the
# container args). Installs the [mcp] serving extra, [vertex] for in-tenancy
# embeddings, and [oauth] for the AS (PyJWT); the serving extra brings
# google-cloud-storage (gs:// index/policy/proposals) and google-genai (Gemini
# synthesis). At startup the service loads the index from BRAIN_INDEX (a gs://
# object in production), verifies OIDC/OAuth, and serves MCP over streamable HTTP,
# exporting OpenTelemetry spans when BRAIN_OTEL is set.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    BRAIN_INDEX=/var/brain/index.json

WORKDIR /app

# Install dependencies first for better layer caching. The production brain reads
# its policy from GCS (BRAIN_POLICY), so config/ is not baked into the image.
COPY pyproject.toml requirements.txt ./
COPY brain_app ./brain_app
RUN pip install --no-cache-dir -e ".[mcp,vertex,oauth]"

# Cloud Run sends traffic to $PORT; the server binds it.
EXPOSE 8080

# Runs as a non-root user for defence in depth.
RUN useradd --create-home --uid 1000 brain
USER brain

CMD ["python", "-m", "brain_app.serving.server"]
