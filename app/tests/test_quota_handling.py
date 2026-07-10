"""Graceful degradation when Gemini's dynamic shared quota is exhausted (429).

The fix for a busy quota is backoff-and-jitter retry (handled by the SDK), but a 429
can still survive under sustained load. These tests pin the user-facing behaviour: an
`answer` degrades to the deterministic extractive result with a clear notice rather
than erroring, and a Studio draft falls back to the raw extract flagged as throttled.
"""

from __future__ import annotations

import pytest

from brain_app.auth import HmacVerifier, encode_hs256
from brain_app.config import load_policy
from brain_app.genai_retry import QUOTA_MESSAGE, is_quota_error
from brain_app.ingest.models import ParsedDoc
from brain_app.models import SearchResult
from brain_app.retrieval.gemini import GeminiSynthesiser
from brain_app.serving import BrainService

SECRET = "test-secret"


def _identity(email="user@bank.com"):
    token = encode_hs256({"sub": email, "email": email, "groups": [], "scope": "read"}, SECRET)
    return HmacVerifier(SECRET).verify(token)


def test_is_quota_error_matches_429_and_resource_exhausted():
    assert is_quota_error(Exception("429 RESOURCE_EXHAUSTED: quota"))
    assert is_quota_error(Exception("HTTP 429 Too Many Requests"))
    assert not is_quota_error(Exception("permission denied"))


def _result(title, text, domain="commons"):
    return SearchResult(
        chunk_id=f"{domain}/{title}#0",
        doc_id=f"{domain}/{title}",
        domain=domain,
        title=title,
        heading="",
        text=text,
        score=1.0,
        via="dense",
    )


def test_answer_degrades_to_extractive_on_quota_error():
    def raise_quota(_prompt: str) -> str:
        raise Exception("429 RESOURCE_EXHAUSTED: dynamic shared quota")

    synth = GeminiSynthesiser(generate=raise_quota)
    results = [_result("fraud", "Real-time fraud detection scores every transaction.")]
    answer = synth.synthesise("how does fraud detection work", results)
    # A grounded, cited answer still comes back, prefixed with the quota notice.
    assert answer.text.startswith(QUOTA_MESSAGE)
    assert answer.citations  # citations preserved from the extractive fallback


def test_answer_reraises_non_quota_errors():
    def boom(_prompt: str) -> str:
        raise RuntimeError("model misconfigured")

    synth = GeminiSynthesiser(generate=boom)
    with pytest.raises(RuntimeError):
        synth.synthesise("q", [_result("t", "body")])


class _QuotaCurator:
    """A curator whose model call is throttled: curate raises a 429."""

    def curate(self, doc: ParsedDoc, known_titles=None) -> ParsedDoc:
        raise Exception("429 RESOURCE_EXHAUSTED")

    def rewrite(self, text: str, instruction: str) -> str:
        raise Exception("429 RESOURCE_EXHAUSTED")


def test_make_draft_flags_quota_when_curation_is_throttled(index, embeddings):
    policy = load_policy(prof="personal")
    svc = BrainService(index, embeddings, policy, curator=_QuotaCurator())
    draft = svc.make_draft(
        _identity(), kind="text", text="Some raw pasted source text about widgets.", curate=True
    )
    assert draft["curated"] is False
    assert draft["quota_degraded"] is True
    # The raw extract is preserved so the user can still edit and create it.
    assert "widgets" in draft["content"]
