"""Durable sign-in audit: one immutable object per Google sign-in, in a GCS bucket.

**Write-once by design.** The AS service account holds only ``roles/storage.objectCreator`` on
the audit bucket, and each record is written with ``if_generation_match=0`` (create-only) under
a unique name -- so the AS can *append* sign-in records but can never overwrite or delete one.
With bucket **object versioning** on, the trail is a tamper-evident, compliance-grade record of
who signed in and when, that outlives Cloud Logging's retention window.

Enabled only when ``BRAIN_AUDIT_BUCKET`` names a bucket; otherwise every call is a no-op, so a
deployment without it (and the tests) never touch GCS. **Best-effort**: any error is swallowed
so an audit write can never block or fail a user's sign-in.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os

_ENV = "BRAIN_AUDIT_BUCKET"


def enabled() -> bool:
    return bool(os.environ.get(_ENV, "").strip())


def record_signin(sub: str, email: str) -> None:
    """Append one immutable record for a Google sign-in."""
    _record(sub, email, "sign-in")


def record_guest() -> None:
    """Append one immutable record for a guest session start (anonymous, no email)."""
    _record("guest", "", "guest-signin")


def _record(sub: str, email: str, event: str) -> None:
    bucket = os.environ.get(_ENV, "").strip()
    if not bucket or not sub:
        return
    with contextlib.suppress(Exception):  # audit is best-effort; never fail a sign-in over it
        from google.cloud import storage

        now = datetime.datetime.now(datetime.UTC)
        ts = now.strftime("%Y-%m-%dT%H-%M-%S-%fZ")  # microseconds -> effectively collision-free
        safe_sub = "".join(c for c in str(sub) if c.isalnum()) or "unknown"
        name = f"signins/{ts}-{safe_sub}.json"
        payload = json.dumps({"ts": now.isoformat(), "sub": sub, "email": email, "event": event})
        blob = storage.Client().bucket(bucket).blob(name)
        # Create-only: refuse to overwrite an existing record (write-once at the API layer too).
        blob.upload_from_string(payload, content_type="application/json", if_generation_match=0)
