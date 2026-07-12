"""Static file server for the Brain Explorer with cache headers that prevent stale
ES-module skew.

The SPA is a set of ES modules that import one another (app.js -> live.js -> auth.js).
Python's plain http.server sends no Cache-Control, so a browser applies heuristic
caching and can hold a stale module against a freshly deployed one, which surfaces as
"X is not a function" when the two versions disagree. This server revalidates code and
data on every load (a cheap 304 when unchanged) and lets only the immutable, hashed
fonts cache for a year.
"""

from __future__ import annotations

import functools
import http.server
import os

_IMMUTABLE = (".woff2", ".woff", ".ttf")


class Handler(http.server.SimpleHTTPRequestHandler):
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
