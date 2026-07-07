"""File attachments: Word text extraction and the ingest_file tool.

A file is parsed to searchable text and the original is kept as a linked attachment.
Personal-space uploads are ungated; team uploads go through the reviewed propose
path (so the write grant still binds).
"""

from __future__ import annotations

import base64
import io
import zipfile

import pytest

from brain_app.auth import identity_from_claims
from brain_app.config import load_policy
from brain_app.ingest.parsers import get_parser
from brain_app.ingest.parsers.docx import DocxParser
from brain_app.serving import (
    AccessError,
    BrainService,
    MemoryGate,
)
from brain_app.serving.attachments import MemoryAttachmentStore, safe_filename

from .conftest import FINSERV

_DOCX_XML = (
    '<?xml version="1.0"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>"
    "<w:p><w:r><w:t>Hello world</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Second paragraph &amp; more</w:t></w:r></w:p>"
    "<w:p></w:p>"
    "</w:body></w:document>"
)


def _docx_bytes(document_xml: str = _DOCX_XML) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _ident(sub, email=None, groups=()):
    return identity_from_claims({"sub": sub, "email": email or sub, "groups": list(groups)})


ADMIN = _ident("admin@example.com", groups=["brain-admins@example.com"])
RECRUITER = _ident("rex@example.com", groups=["recruiting@example.com"])


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# --- Word extraction -------------------------------------------------------------


def test_docx_parser_extracts_paragraph_text():
    parsed = DocxParser().parse(_docx_bytes(), "application/vnd...docx")
    assert parsed.body == "Hello world\n\nSecond paragraph & more"


def test_docx_parser_rejects_non_docx():
    with pytest.raises(ValueError):
        DocxParser().parse(b"not a zip", "application/octet-stream")


def test_get_parser_routes_docx():
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert isinstance(get_parser(mime), DocxParser)


def test_safe_filename_strips_paths_and_unsafe_chars():
    assert safe_filename("../../etc/pa ss?.pdf") == "pa_ss_.pdf"


# --- ingest_file -----------------------------------------------------------------


@pytest.fixture
def svc(index, embeddings):
    return BrainService(
        index,
        embeddings,
        load_policy(prof="personal"),
        gate=MemoryGate(),
        note_gate=MemoryGate(),
        attachment_store=MemoryAttachmentStore(),
    )


def test_markdown_file_lands_in_personal_space_ungated(svc):
    owner = _ident("sub-att", email="a@example.com")
    res = svc.ingest_file(
        owner, filename="my-notes.md", content_base64=_b64(b"# Notes\n\nA thought.")
    )
    assert res.status in {"proposed", "saved"}
    proposal = svc.note_gate.proposals[0]
    assert proposal.domain == "personal:sub-att"
    # The original is kept and linked from the generated document.
    assert svc.attachment_store.saved  # the file bytes were stored
    assert "Ingested from" in proposal.content
    assert "A thought." in proposal.content


def test_docx_file_is_extracted_and_ingested(svc):
    owner = _ident("sub-att", email="a@example.com")
    svc.ingest_file(owner, filename="report.docx", content_base64=_b64(_docx_bytes()))
    proposal = svc.note_gate.proposals[0]
    assert "Hello world" in proposal.content and "Second paragraph" in proposal.content


def test_team_upload_goes_through_the_reviewed_path(svc):
    # An admin (write on finserv) uploads into the team domain -> the propose gate.
    svc.ingest_file(ADMIN, filename="brief.txt", domain=FINSERV, content_base64=_b64(b"team brief"))
    assert svc.gate.proposals[0].domain == FINSERV
    assert svc.note_gate.proposals == []  # not the personal path


def test_team_upload_without_write_is_refused(svc):
    from brain_app.serving import AccessError as _AccessError

    with pytest.raises(_AccessError):  # recruiter cannot write finserv
        svc.ingest_file(RECRUITER, filename="x.txt", domain=FINSERV, content_base64=_b64(b"nope"))


def test_unsupported_file_type_is_refused(svc):
    owner = _ident("sub-att")
    with pytest.raises(AccessError):
        svc.ingest_file(owner, filename="malware.exe", content_base64=_b64(b"MZ"))


def test_non_base64_content_is_refused(svc):
    owner = _ident("sub-att")
    with pytest.raises(AccessError):
        svc.ingest_file(owner, filename="x.md", content_base64="not valid base64!!")


def test_anonymous_caller_cannot_ingest(svc):
    with pytest.raises(AccessError):
        svc.ingest_file(identity_from_claims({}), filename="x.md", content_base64=_b64(b"hi"))
