"""The AI-platform manifest: model inventory + versioned prompts."""

from __future__ import annotations

from brain_app.inventory import manifest, models, prompts


def test_model_inventory_lists_the_models_in_use():
    ids = {m["id"] for m in models()}
    assert {"gemini-2.5-flash", "text-embedding-005"} <= ids
    for entry in models():
        # Each model is governed: purpose, provider and approval status are recorded.
        assert entry["purpose"] and entry["provider"] and entry["status"]


def test_prompts_are_versioned_and_hashed():
    by_name = {p["name"]: p for p in prompts()}
    assert {"researcher", "curator", "coordinator"} == set(by_name)
    for entry in by_name.values():
        assert entry["version"] and len(entry["sha"]) == 12


def test_manifest_combines_models_and_prompts():
    m = manifest()
    assert m["models"] and m["prompts"]
