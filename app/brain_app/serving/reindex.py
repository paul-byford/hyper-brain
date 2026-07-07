"""Trigger the in-tenancy index rebuild after a live write.

A personal note (``add_note``), a file upload, or an accepted proposal lands content
in the corpus bucket, but nothing is searchable until the index Job rebuilds. Those
paths call the reindexer here. It is fire-and-forget: the Cloud Run Job runs to
completion in the background and the brain reloads the index within its TTL, so the
caller is not blocked. Injectable, so the offline core and tests stay cloud-free.

This deliberately rebuilds the whole index on each live write for near-instant
feedback; incremental (embed only changed chunks) is a later optimisation.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class Reindexer(Protocol):
    def trigger(self) -> None: ...


class MemoryReindexer:
    """In-process no-op; the default and the test double (counts calls)."""

    def __init__(self) -> None:
        self.triggers = 0

    def trigger(self) -> None:
        self.triggers += 1


class RunJobReindexer:
    """Runs the index Cloud Run Job via the Admin API, using the brain SA's own
    credentials (it holds run.invoker on the Job). Non-blocking: it starts the
    execution and returns."""

    def __init__(self, indexer_job: str) -> None:
        self.indexer_job = indexer_job  # projects/P/locations/L/jobs/J

    def trigger(self) -> None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)
        session.post(f"https://run.googleapis.com/v2/{self.indexer_job}:run").raise_for_status()


def get_reindexer() -> Reindexer:
    """A live Job trigger when the indexer Job is configured (deployed), else no-op."""
    job = os.environ.get("BRAIN_INDEXER_JOB")
    return RunJobReindexer(job) if job else MemoryReindexer()
