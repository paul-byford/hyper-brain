"""The ADK model for the team's agents, pinned to Vertex's global Gemini endpoint.

Each agent's reasoning call goes to the ``global`` endpoint rather than a single region's free
dynamic shared quota, which pools capacity across regions and so is far less likely to 429 an
agent run mid-flow (a busy ``europe-west2`` was hanging runs on the researcher). Only the prompt
and response transit globally; sessions, memory, embeddings and the corpus stay in
``GOOGLE_CLOUD_LOCATION``. The endpoint is ``gemini_location()`` (BRAIN_GEMINI_LOCATION), so it
can be pinned back to a region without touching code.

google-adk / google-genai are imported lazily so the offline core never loads them.
"""

from __future__ import annotations

import functools
import os


def agent_model(model: str):
    """An ADK ``Gemini`` on the global endpoint, carrying the shared 429/503 retry policy.

    Falls back to the plain model name on an older ADK that lacks these hooks, so the agent
    still runs (just against the default regional endpoint) rather than failing to build."""
    from ..genai_retry import gemini_location, retry_options

    try:
        from google.adk.models import Gemini
    except Exception:
        return model

    location = gemini_location()

    class _GlobalGemini(Gemini):
        # Override the client the same way ADK's own docs prescribe for a custom location,
        # keeping the base's tracking headers + retry policy.
        @functools.cached_property
        def api_client(self):
            from google.genai import Client, types

            return Client(
                vertexai=True,
                project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                location=location,
                http_options=types.HttpOptions(
                    headers=self._tracking_headers(),
                    retry_options=self.retry_options,
                ),
            )

    try:
        return _GlobalGemini(model=model, retry_options=retry_options())
    except (TypeError, ValueError):
        return model
