"""Phase 9 wiring: Gemini synthesis, cloud proposal gate, GCS-backed policy,
Document AI parser, and corpus gs:// input. All hermetic: model calls are injected
and the storage client is faked, so no cloud is touched."""

from __future__ import annotations

import pytest

from brain_app import config
from brain_app.auth.identity import identity_from_claims
from brain_app.config import Grant, Policy, policy_source
from brain_app.ingest.parsers import get_parser
from brain_app.ingest.parsers.pdf import DocumentAiParser
from brain_app.models import SearchResult
from brain_app.retrieval.answer import ExtractiveSynthesiser, get_synthesiser
from brain_app.retrieval.gemini import GeminiSynthesiser
from brain_app.serving import BrainService, GcsProposalGate, MemoryGate, get_gate
from brain_app.serving.proposals import GitBranchGate, build_proposal

from .conftest import FINSERV, RECRUITMENT


def _hits():
    return [
        SearchResult(
            "c0",
            "d/x",
            FINSERV,
            "Fraud",
            "Feature freshness",
            "Fresh features catch fraud.",
            1.0,
            "hybrid",
        ),
        SearchResult(
            "c1", "d/y", FINSERV, "Vectors", "In-tenancy", "Vectors stay in tenancy.", 0.9, "hybrid"
        ),
    ]


# --- Gemini synthesiser -------------------------------------------------------


def test_gemini_synthesiser_grounds_and_keeps_gaps():
    seen = {}

    def fake_generate(prompt):
        seen["prompt"] = prompt
        return "Fresh features catch fraud [Fraud]."

    result = GeminiSynthesiser(generate=fake_generate).synthesise(
        "how to catch quantum fraud", _hits()
    )
    assert "Fraud" in result.text
    # The prompt is grounded on the retrieved context and the question.
    assert "Feature freshness" in seen["prompt"] and "quantum fraud" in seen["prompt"]
    assert result.citations == _hits()
    assert result.used_domains == [FINSERV]
    # The deterministic gap statement survives: "quantum" is unsupported.
    assert "quantum" in result.gaps


def test_gemini_synthesiser_empty_results():
    out = GeminiSynthesiser(generate=lambda p: "unused").synthesise("q", [])
    assert out.citations == [] and "don't have" in out.text


def test_get_synthesiser_selection():
    assert isinstance(get_synthesiser("extractive"), ExtractiveSynthesiser)
    assert isinstance(get_synthesiser("gemini"), GeminiSynthesiser)
    with pytest.raises(ValueError, match="unknown synthesiser"):
        get_synthesiser("crystal-ball")


# --- Proposal gate selection + cloud gate -------------------------------------


def test_get_gate_selection(monkeypatch):
    assert isinstance(get_gate("memory"), MemoryGate)
    assert isinstance(get_gate("git"), GitBranchGate)
    monkeypatch.setenv("BRAIN_PROPOSALS_BUCKET", "brain-corpus")
    assert isinstance(get_gate("gcs"), GcsProposalGate)
    monkeypatch.delenv("BRAIN_PROPOSALS_BUCKET")
    with pytest.raises(ValueError, match="BRAIN_PROPOSALS_BUCKET"):
        get_gate("gcs")


def test_gcs_gate_stages_to_review_prefix(monkeypatch):
    uploaded = {}

    class _Blob:
        def __init__(self, name):
            self.name = name

        def upload_from_string(self, data):
            uploaded["name"] = self.name
            uploaded["data"] = data

    class _Bucket:
        def blob(self, name):
            return _Blob(name)

    class _Client:
        def bucket(self, name):
            uploaded["bucket"] = name
            return _Bucket()

    import google.cloud.storage as gcs

    monkeypatch.setattr(gcs, "Client", _Client)

    proposal = build_proposal(
        domain=FINSERV, title="Shadow Deploys", content="# X\n\nbody\n", author="a@b.com"
    )
    result = GcsProposalGate("brain-corpus").submit(proposal)

    assert uploaded["bucket"] == "brain-corpus"
    assert uploaded["name"].startswith(f"proposals/{FINSERV}/shadow-deploys-")
    assert result.path.startswith("gs://brain-corpus/proposals/")
    assert "# X" in uploaded["data"]


# --- Policy source (grant rollout without redeploy) ---------------------------


def test_policy_source_caches_then_reloads(monkeypatch):
    calls = {"n": 0}
    real = config.load_policy

    def counting(path=None, prof=None):
        calls["n"] += 1
        return real(prof="personal")

    monkeypatch.setattr(config, "load_policy", counting)

    cached = policy_source(ttl=1000)
    cached()
    cached()
    assert calls["n"] == 1  # within TTL: one load

    always = policy_source(ttl=-1)
    always()
    always()
    assert calls["n"] == 3  # TTL expired each call: two more loads


def test_service_resolves_policy_per_request(index, embeddings):
    # Two policies; flipping the source is how a grant becomes visible live.
    finserv_only = Policy(1, (FINSERV, RECRUITMENT), (Grant("group:x@e.com", (FINSERV,)),))
    both = Policy(1, (FINSERV, RECRUITMENT), (Grant("group:x@e.com", (FINSERV, RECRUITMENT)),))
    current = [finserv_only]
    svc = BrainService(index, embeddings, finserv_only, policy_source=lambda: current[0])
    ident = identity_from_claims({"sub": "u", "groups": ["x@e.com"]})

    assert svc.list_domains(ident) == [FINSERV]
    current[0] = both  # a grant just widened access
    assert svc.list_domains(ident) == sorted([FINSERV, RECRUITMENT])


# --- Document AI parser -------------------------------------------------------


def test_document_ai_parser_uses_injected_process():
    parser = DocumentAiParser(
        processor="projects/p/locations/l/processors/x", process=lambda c, m: "Parsed PDF text."
    )
    assert parser.parse(b"%PDF-1.7", "application/pdf").body == "Parsed PDF text."


def test_get_parser_selects_document_ai_when_configured(monkeypatch):
    monkeypatch.setenv("BRAIN_DOCAI_PROCESSOR", "projects/p/locations/l/processors/x")
    assert isinstance(get_parser("application/pdf"), DocumentAiParser)
    monkeypatch.delenv("BRAIN_DOCAI_PROCESSOR")


# --- Ingest lands to a gs:// corpus (the in-tenancy cloud path) ----------------


def test_ingest_lands_to_gcs_corpus(tmp_path, monkeypatch):
    from brain_app.ingest import ingest_source
    from brain_app.ingest.sources import SourceConfig

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "note.md").write_text("---\ntitle: Cloud Note\n---\n\n# Cloud Note\n\nBody.\n", "utf-8")

    blobs: dict[str, str] = {}

    class _Blob:
        def __init__(self, name):
            self.name = name

        def exists(self):
            return self.name in blobs

        def download_as_text(self):
            return blobs[self.name]

        def upload_from_string(self, data):
            blobs[self.name] = data

    class _Bucket:
        def blob(self, name):
            return _Blob(name)

    class _Client:
        def bucket(self, name):
            return _Bucket()

    import google.cloud.storage as gcs

    monkeypatch.setattr(gcs, "Client", _Client)

    source = SourceConfig(
        id="raw-test",
        type="local",
        domain=FINSERV,
        curate=False,
        options={"path": str(raw), "glob": "*.md"},
    )
    report = ingest_source(
        source, "gs://brain-corpus", state_dir=str(tmp_path / "state"), run_id="r", now="n"
    )

    assert report.written == 1
    name = f"{FINSERV}/cloud-note.md"
    assert name in blobs  # landed into the bucket under <domain>/<slug>.md
    assert f"domain: {FINSERV}" in blobs[name]
    assert "source: raw-test" in blobs[name]
