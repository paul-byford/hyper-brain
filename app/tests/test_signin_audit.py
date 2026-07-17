"""Durable sign-in audit: a no-op when unconfigured, write-once when on.

What is ours to keep correct: without ``BRAIN_AUDIT_BUCKET`` nothing is written (and no GCS
call is made), and when configured each record is create-only (``if_generation_match=0``) under
a ``signins/`` name with the right event -- so the trail can be appended to but never tampered.
"""

from __future__ import annotations

from brain_app.oauth import audit


def test_disabled_is_a_noop(monkeypatch):
    monkeypatch.delenv("BRAIN_AUDIT_BUCKET", raising=False)
    assert not audit.enabled()
    # Must not raise and must not touch GCS (storage.Client would blow up if it were called).
    import google.cloud.storage as storage

    monkeypatch.setattr(storage, "Client", lambda: (_ for _ in ()).throw(AssertionError("called")))
    audit.record_signin("117876193665950488017", "a@b.com")
    audit.record_guest()


def test_records_are_write_once_with_event(monkeypatch):
    monkeypatch.setenv("BRAIN_AUDIT_BUCKET", "hb-audit")
    recorded, names = [], []

    class _Blob:
        def upload_from_string(self, data, content_type=None, if_generation_match=None):
            import json

            recorded.append({"data": json.loads(data), "if_gen": if_generation_match})

    class _Bucket:
        def blob(self, name):
            names.append(name)
            return _Blob()

    class _Client:
        def bucket(self, name):
            return _Bucket()

    import google.cloud.storage as storage

    monkeypatch.setattr(storage, "Client", lambda: _Client())

    audit.record_signin("sub-xyz", "user@example.com")
    audit.record_guest()

    assert len(recorded) == 2
    assert recorded[0]["data"]["event"] == "sign-in"
    assert recorded[0]["data"]["email"] == "user@example.com"
    assert recorded[1]["data"]["event"] == "guest-signin"
    assert recorded[1]["data"]["sub"] == "guest" and recorded[1]["data"]["email"] == ""
    assert all(r["if_gen"] == 0 for r in recorded)  # create-only == write-once
    assert all(n.startswith("signins/") and n.endswith(".json") for n in names)
