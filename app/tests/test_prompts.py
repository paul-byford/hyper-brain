"""The versioned prompt registry: prompts are named, versioned, content-hashed."""

from __future__ import annotations

from brain_app.prompts import Prompt, get_prompt, prompt, registry


def test_registry_has_versioned_hashed_prompts():
    assert {p.name for p in registry()} == {"researcher", "curator", "coordinator"}
    for entry in registry():
        assert entry.version  # a semantic version is pinned
        assert len(entry.sha) == 12  # a stable content hash identifies the text
        assert prompt(entry.name) == entry.text  # prompt() returns the active text


def test_hash_is_content_addressed():
    text = get_prompt("researcher").text
    assert Prompt("x", "1", text).sha == get_prompt("researcher").sha
    assert Prompt("x", "1", text + " tweak").sha != get_prompt("researcher").sha
