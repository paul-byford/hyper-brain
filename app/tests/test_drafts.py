"""Draft-first ingestion: the SSRF-hardened URL fetch, main-content extraction, and
the service make_draft that turns a URL/file/text into an editable draft (no write).
"""

from __future__ import annotations

import base64

import pytest

from brain_app.auth import HmacVerifier, encode_hs256
from brain_app.config import load_policy
from brain_app.ingest.curate import PassthroughCurator
from brain_app.serving import BrainService
from brain_app.serving.drafts import UrlFetchError, extract_main_text, fetch_url

SECRET = "test-secret"


@pytest.fixture
def policy():
    return load_policy(prof="personal")


def _identity(email="user@bank.com"):
    token = encode_hs256({"sub": email, "email": email, "groups": [], "scope": "read"}, SECRET)
    return HmacVerifier(SECRET).verify(token)


def test_fetch_url_rejects_non_http_schemes():
    with pytest.raises(UrlFetchError):
        fetch_url("file:///etc/passwd")


def test_fetch_url_blocks_internal_and_metadata_addresses():
    for bad in (
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://localhost/admin",
        "http://127.0.0.1:8080/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
    ):
        with pytest.raises(UrlFetchError):
            fetch_url(bad)


def test_fetch_url_uses_injected_opener_for_public():
    body = b"<html><title>T</title><body><article><p>Hello world body</p></article></body></html>"
    data, mime = fetch_url("https://example.com/a", opener=lambda u: (body, "text/html"))
    assert b"Hello world" in data and "html" in mime


def test_extract_main_text_drops_boilerplate():
    html = (
        b"<html><head><title>My Page | Site</title></head><body>"
        b"<nav>Home About Contact</nav><script>var x=1;</script>"
        b"<main><h1>Heading</h1><p>The real article content is here.</p></main>"
        b"<footer>copyright 2026</footer></body></html>"
    )
    title, body = extract_main_text(html)
    assert title == "My Page"
    assert "real article content" in body
    assert "Home About" not in body
    assert "copyright" not in body
    assert "var x" not in body


def _service(index, embeddings, policy):
    # Passthrough curator: deterministic, no cloud (the "clean up with AI" no-op tier).
    return BrainService(index, embeddings, policy, curator=PassthroughCurator())


def test_make_draft_from_text_titles_from_heading(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    draft = svc.make_draft(_identity(), kind="text", text="# My note\n\nSome content.", curate=True)
    assert draft["title"] == "My note"
    assert draft["content"] == "# My note\n\nSome content."  # passthrough leaves it unchanged
    assert draft["curated"] is False
    assert draft["source_url"] is None


def test_make_draft_from_url_extracts_and_keeps_source(index, embeddings, policy, monkeypatch):
    html = (
        b"<html><title>Fraud article</title><body><main>"
        b"<p>Fresh features catch fraud fast.</p></main></body></html>"
    )
    monkeypatch.setattr("brain_app.serving.drafts.fetch_url", lambda u: (html, "text/html"))
    svc = _service(index, embeddings, policy)
    draft = svc.make_draft(_identity(), kind="url", url="https://x.example/a", curate=False)
    assert draft["source_url"] == "https://x.example/a"
    assert "catch fraud" in draft["content"]
    assert draft["title"] == "Fraud article"


def test_make_draft_from_file_parses_markdown(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    raw = base64.b64encode(b"# Uploaded\n\nBody text.").decode()
    draft = svc.make_draft(
        _identity(), kind="file", filename="notes.md", content_base64=raw, curate=False
    )
    assert "Body text." in draft["content"]


def test_make_draft_empty_source_is_a_clean_error(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    with pytest.raises(ValueError):
        svc.make_draft(_identity(), kind="text", text="   ", curate=False)


def test_documentai_endpoint_is_regional():
    from brain_app.ingest.parsers.pdf import _endpoint_for

    assert _endpoint_for("projects/p/locations/eu/processors/x") == "eu-documentai.googleapis.com"
    assert _endpoint_for("projects/p/locations/us/processors/x") is None
    assert (
        _endpoint_for("projects/p/locations/europe-west2/processors/x")
        == "europe-west2-documentai.googleapis.com"
    )


def test_make_draft_survives_a_failing_curator(index, embeddings, policy):
    # Curation is best-effort: a model error/safety block must not 500 the draft.
    class _Boom:
        def curate(self, doc, known_titles=None):
            raise RuntimeError("blocked by safety")

    svc = BrainService(index, embeddings, policy, curator=_Boom())
    draft = svc.make_draft(_identity(), kind="text", text="raw pasted content", curate=True)
    assert draft["curated"] is False
    assert "raw pasted content" in draft["content"]


def test_docai_page_limit_message_is_friendly():
    from brain_app.ingest.parsers.pdf import _docai_message

    raw = "400 Document pages exceed the limit: 30 got 64 [reason: PAGE_LIMIT_EXCEEDED ...]"
    msg = _docai_message(Exception(raw))
    assert "30 pages" in msg
    assert "Split" in msg
    assert "PAGE_LIMIT_EXCEEDED" not in msg  # the raw error code is not surfaced


def test_fetch_url_http_error_message_is_friendly():
    from brain_app.serving.drafts import _http_error_message

    assert "blocked" in _http_error_message(403).lower()
    assert "paste" in _http_error_message(403).lower()
    assert "found" in _http_error_message(404).lower()
    assert "429" in _http_error_message(429)


def test_split_tags_extracts_trailing_line():
    from brain_app.serving.service import BrainService

    body, tags = BrainService._split_tags("# T\n\nbody\n\nTags: AI, ML, fraud")
    assert tags == ["ai", "ml", "fraud"]
    assert "Tags:" not in body and body.endswith("body")
    body2, tags2 = BrainService._split_tags("# T\n\nbody")
    assert tags2 == [] and body2 == "# T\n\nbody"


def test_make_draft_parses_tags_from_curation(index, embeddings, policy):
    from brain_app.ingest.models import ParsedDoc

    class _Curator:
        def curate(self, doc, known_titles=None):
            return ParsedDoc(body="# Clean\n\n## Summary\n\npoints\n\nTags: alpha, beta")

        def rewrite(self, text, instruction):
            return text

    svc = BrainService(index, embeddings, policy, curator=_Curator())
    draft = svc.make_draft(_identity(), kind="text", text="raw source", curate=True)
    assert draft["curated"] is True
    assert draft["tags"] == ["alpha", "beta"]
    assert "Tags:" not in draft["content"]
    assert draft["title"] == "Clean"


def test_simplify_text_is_best_effort(index, embeddings, policy):
    from brain_app.ingest.curate import PassthroughCurator

    svc = BrainService(index, embeddings, policy, curator=PassthroughCurator())
    out = svc.simplify_text(_identity(), "# Complex\n\njargon here")
    assert "Complex" in out["content"]
