# Minimal image for the brain MCP service (Cloud Run, scale-to-zero).
#
# It installs the offline core plus the [mcp] serving extra. At startup the
# service loads the index artefact from BRAIN_INDEX (a local path or, in
# production, a gs:// object streamed from the domain-partitioned bucket) and
# serves MCP over streamable HTTP. OpenTelemetry span export is wired in the
# observability phase (IMPLEMENTATION-PLAN.md phase 8); the app already keeps a
# clean seam for it.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    BRAIN_INDEX=/var/brain/index.json

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml requirements.txt ./
COPY brain_app ./brain_app
RUN pip install --no-cache-dir -e ".[mcp]"

# Cloud Run sends traffic to $PORT; the server binds it.
EXPOSE 8080

# Runs as a non-root user for defence in depth.
RUN useradd --create-home --uid 1000 brain
USER brain

CMD ["python", "-m", "brain_app.serving.server"]
