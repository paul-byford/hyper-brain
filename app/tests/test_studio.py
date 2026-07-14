"""Agent Studio: a custom specialist is admin-gated **behaviour, not access**.

What is ours to keep correct: only a team moderator may author/preview/delete shared
specialists (guests never), the name + tool allow-list are validated, and a saved spec becomes
a routing line the coordinator sees. The run-time guarantee that a custom agent's tools are
domain-scoped to the caller is inherited from BrainService (its tools are the same caller-bound
callables the researcher uses) -- these hermetic tests pin the gating and validation.
"""

from __future__ import annotations

import pytest

from brain_app.agent.studio import AgentSpec, MemoryAgentStore
from brain_app.auth import HmacVerifier, Identity, encode_hs256
from brain_app.config import load_policy
from brain_app.serving import AccessError, BrainService
from brain_app.serving.agent_run import _coordinator_instruction, _custom_specs

SECRET = "test-secret"


@pytest.fixture(scope="module")
def policy():
    return load_policy(prof="personal")


def _identity(groups, email="user@bank.com"):
    claims = {"sub": email, "email": email, "groups": groups, "scope": "read propose"}
    return HmacVerifier(SECRET).verify(encode_hs256(claims, SECRET))


def _guest() -> Identity:
    return Identity(
        subject="guest:x", email="", principals=(), scopes=frozenset(), claims={"guest": True}
    )


def _spec(name="reviewer", tools=("search", "get_document")):
    return {
        "name": name,
        "description": "checking proposals against domain policy",
        "instruction": "You review proposals.",
        "tools": list(tools),
    }


def test_spec_validation_rejects_reserved_names_and_unknown_tools():
    bad_specs = [
        _spec(name="researcher"),  # reserved built-in
        _spec(name="Bad Name"),  # not snake_case
        _spec(tools=("search", "rm")),  # unknown tool
        _spec(tools=()),  # no tools
    ]
    for bad in bad_specs:
        with pytest.raises(ValueError):
            AgentSpec.from_dict(bad).validate()
    AgentSpec.from_dict(_spec()).validate()  # a valid spec does not raise


def test_memory_store_roundtrip():
    store = MemoryAgentStore()
    store.put(AgentSpec.from_dict(_spec()))
    store.put(AgentSpec.from_dict(_spec(name="summariser", tools=("answer",))))
    assert [s.name for s in store.all()] == ["reviewer", "summariser"]
    store.delete("reviewer")
    assert [s.name for s in store.all()] == ["summariser"]


def test_only_a_team_moderator_may_author(index, embeddings, policy):
    svc = BrainService(index, embeddings, policy, agent_store=MemoryAgentStore())
    admin = _identity(["brain-admins@example.com"])  # explicit team write grant
    plain = _identity([])  # only the commons wildcard -- not a moderator

    assert svc.is_studio_admin(admin) is True
    assert svc.is_studio_admin(plain) is False
    assert svc.is_studio_admin(_guest()) is False

    with pytest.raises(AccessError):
        svc.save_custom_agent(plain, _spec())
    with pytest.raises(AccessError):
        svc.delete_custom_agent(plain, "reviewer")

    assert svc.save_custom_agent(admin, _spec())["status"] == "saved"
    listed = svc.list_custom_agents(plain)  # visible to everyone (shared team)...
    assert any(a["name"] == "reviewer" for a in listed["agents"])
    assert listed["can_edit"] is False  # ...but a plain user cannot edit
    assert "propose_document" in listed["tools"]


def test_a_saved_spec_becomes_a_coordinator_routing_line(index, embeddings, policy):
    svc = BrainService(index, embeddings, policy, agent_store=MemoryAgentStore())
    admin = _identity(["brain-admins@example.com"])
    assert _custom_specs(svc) == []  # none yet -> base coordinator prompt unchanged
    base = _coordinator_instruction(svc)
    svc.save_custom_agent(admin, _spec())
    extended = _coordinator_instruction(svc)
    assert "reviewer" in extended and "checking proposals" in extended
    assert len(extended) > len(base)
