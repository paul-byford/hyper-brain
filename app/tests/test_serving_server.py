"""Pillar 1: the MCP binding registers the tool surface and gates on the bearer header.

Requires the [mcp] serving extra; skipped cleanly if it is not installed.
"""

from __future__ import annotations

import asyncio
import types

import pytest

pytest.importorskip("mcp")

from brain_app.auth import HmacVerifier  # noqa: E402
from brain_app.config import load_policy  # noqa: E402
from brain_app.serving import BrainService  # noqa: E402
from brain_app.serving.server import _bearer_from_context, build_server  # noqa: E402


def _ctx(headers: dict) -> types.SimpleNamespace:
    request = types.SimpleNamespace(headers=headers)
    return types.SimpleNamespace(request_context=types.SimpleNamespace(request=request))


def test_bearer_extracted_from_header():
    assert _bearer_from_context(_ctx({"authorization": "Bearer abc.def.ghi"})) == "abc.def.ghi"


def test_missing_or_malformed_bearer_refused():
    with pytest.raises(PermissionError):
        _bearer_from_context(_ctx({}))
    with pytest.raises(PermissionError):
        _bearer_from_context(_ctx({"authorization": "Basic abc"}))


def test_server_registers_the_tools(index, embeddings):
    service = BrainService(index, embeddings, load_policy(prof="personal"))
    server = build_server(service, HmacVerifier("s"))
    tool_names = {t.name for t in asyncio.run(server.list_tools())}
    assert tool_names == {
        "list_domains",
        "my_spaces",
        "search",
        "answer",
        "get_document",
        "propose_document",
        "add_note",
        "ingest_file",
        "share",
        "unshare",
        "list_shares",
    }
