"""Static file server for the Brain Explorer with cache headers that prevent stale
ES-module skew, and runtime-injected app config.

Two jobs:

1. **Cache headers.** The SPA is a set of ES modules that import one another
   (app.js -> live.js -> auth.js). Python's plain http.server sends no Cache-Control, so a
   browser applies heuristic caching and can hold a stale module against a freshly deployed
   one ("X is not a function"). This server revalidates code and data on every load (a cheap
   304 when unchanged) and lets only the immutable, hashed fonts cache for a year.

2. **Config from the environment.** ``data/config.json`` carries the live URLs
   (api_url/auth_url/mcp_url) that flip the app from demo to live mode. Baking that file
   into the image made the deployed mode depend on whatever happened to be in ``ui/data`` at
   build time -- which the exporter and the UI tests overwrite with demo values. Instead we
   serve ``data/config.json`` from ``BRAIN_UI_{API,AUTH,MCP}_URL`` when any is set (Terraform
   sets them on the Cloud Run service from the known service URLs), so the deployed config is
   declarative and immune to the baked file. With none set (local ``python serve.py``), we
   fall back to the baked file, so local demo mode still works.
"""

from __future__ import annotations

import functools
import http.server
import json
import os

_IMMUTABLE = (".woff2", ".woff", ".ttf")
_CONFIG_PATH = "/data/config.json"


def _env_config() -> dict | None:
    """The live config from env, or None to fall back to the baked ``data/config.json``."""
    api = os.environ.get("BRAIN_UI_API_URL", "")
    auth = os.environ.get("BRAIN_UI_AUTH_URL", "")
    mcp = os.environ.get("BRAIN_UI_MCP_URL", "")
    if not (api or auth or mcp):
        return None
    # api_url + auth_url set -> live mode; mcp_url powers the connector modal.
    return {"mcp_url": mcp, "auth_url": auth, "api_url": api}


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == _CONFIG_PATH:
            config = _env_config()
            if config is not None:
                self._send_json(config)
                return
        super().do_GET()

    def _send_json(self, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()  # adds Cache-Control (revalidate) via the override below
        self.wfile.write(body)

    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.endswith(_IMMUTABLE):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            # Code, HTML and the exported data snapshot: always revalidate.
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    handler = functools.partial(Handler, directory="/ui")
    http.server.HTTPServer(("", port), handler).serve_forever()
