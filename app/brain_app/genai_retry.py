"""Shared Gemini retry policy: exponential backoff with jitter on 429 / 503.

Vertex Gemini runs on dynamic shared quota, so a transient ``429 RESOURCE_EXHAUSTED``
is expected under load rather than a sign of a too-small quota. Google's guidance is
to ride it out with exponential backoff and jitter instead of requesting an increase
(https://docs.cloud.google.com/vertex-ai/generative-ai/docs/error-code-429). The
google-genai SDK implements exactly that when given ``HttpRetryOptions``, and ADK's
``Gemini`` model accepts the same object, so every Gemini caller in the brain
(synthesis, curation, and the live agent) shares this one policy.

Lazy import: ``google.genai`` is only needed when a real Gemini call is about to run,
so the offline core and its tests never import it.
"""

from __future__ import annotations

import os

# Five attempts across ~1s, 2s, 4s, 8s, 16s (each perturbed by jitter) rides out a
# per-minute quota blip without making a stuck request wait too long. 429 (quota) and
# 503 (transient backend) are the retryable statuses; 4xx client errors are not.
_ATTEMPTS = 5
_INITIAL_DELAY = 1.0
_MAX_DELAY = 32.0
_EXP_BASE = 2.0
_JITTER = 1.0
_RETRY_STATUS = [429, 503]

# Shown to the user when a 429 survives the backoff-and-jitter retries. This demo runs
# on Vertex's free dynamic shared quota, so under concurrent test use Gemini can stay
# busy; the message is honest about that rather than looking like a bug.
QUOTA_MESSAGE = (
    "Gemini's shared quota is busy right now, so this AI step was skipped. This demo "
    "runs on Vertex's free dynamic quota, which throttles under load. Please try again "
    "in a moment."
)


def gemini_location() -> str:
    """The region for Gemini *generative* calls (agent reasoning, answer synthesis, curation).

    Defaults to Vertex's ``global`` endpoint, which pools capacity across regions and so has
    far higher availability than any single region's free dynamic shared quota -- a busy region
    can otherwise 429 an agent run mid-flow. Only the prompt and response transit this endpoint;
    embeddings, sessions, memory and the corpus all stay in ``GOOGLE_CLOUD_LOCATION``
    (europe-west2). Override with ``BRAIN_GEMINI_LOCATION`` (e.g. back to a specific region)."""
    return os.environ.get("BRAIN_GEMINI_LOCATION", "global")


def is_quota_error(exc: BaseException) -> bool:
    """True if an exception is a Gemini rate-limit / quota exhaustion (429)."""
    text = str(exc)
    return "RESOURCE_EXHAUSTED" in text or "429" in text


def retry_options():
    """The shared ``HttpRetryOptions`` (backoff + jitter on 429/503)."""
    from google.genai import types

    return types.HttpRetryOptions(
        attempts=_ATTEMPTS,
        initial_delay=_INITIAL_DELAY,
        max_delay=_MAX_DELAY,
        exp_base=_EXP_BASE,
        jitter=_JITTER,
        http_status_codes=list(_RETRY_STATUS),
    )


def http_options(timeout_ms: int | None = None):
    """An ``HttpOptions`` carrying the shared retry policy (and an optional timeout),
    for building a ``genai.Client``."""
    from google.genai import types

    kwargs = {"retry_options": retry_options()}
    if timeout_ms is not None:
        kwargs["timeout"] = timeout_ms
    return types.HttpOptions(**kwargs)
