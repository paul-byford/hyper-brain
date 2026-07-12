# Image for the Brain Explorer (Cloud Run, IAM-gated). A dependency-free static
# SPA served by Python's http.server. The exported data (data/index.json,
# data/policy.json) is baked in at build time by `brain up`, which runs the
# exporter first; re-run `brain up` to refresh the snapshot. The UI holds no
# secrets and enforces nothing (ARCHITECTURE.md section 9).
FROM python:3.13-slim

ENV PORT=8080
WORKDIR /ui
COPY . /ui

RUN useradd --create-home --uid 1000 ui
USER ui

EXPOSE 8080
# serve.py adds Cache-Control so redeployed ES modules never skew against stale ones.
CMD ["python", "serve.py"]
