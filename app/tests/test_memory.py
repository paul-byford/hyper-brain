"""User-scoped memory: isolation by design.

The live cross-user guarantee (user A's memory never surfaces to user B) is enforced by
Agent Engine Memory Bank scoping every query to a ``user_id``. What is load-bearing *and*
ours to keep correct is that the ``user_id`` is **always the verified subject, derived
server-side** (never a client parameter), and that **guests** and unconfigured deployments
persist and recall nothing. These hermetic tests pin exactly that, so a regression that let
memory cross users (or leak for a guest) fails the build with no cloud call.
"""

from __future__ import annotations

import asyncio

from brain_app.auth import Identity
from brain_app.serving import memory


def _identity(subject: str, guest: bool = False) -> Identity:
    return Identity(
        subject=subject,
        email=f"{subject}@example.com",
        principals=(),
        scopes=frozenset(),
        claims={"guest": True} if guest else {},
    )


class _FakeMem:
    """Records the user_id each call was scoped to; returns one memory on search."""

    def __init__(self):
        self.searched_user_ids: list[str] = []
        self.stored = 0

    async def search_memory(self, *, app_name, user_id, query):
        self.searched_user_ids.append(user_id)

        class _Entry:
            content = type("C", (), {"parts": [type("P", (), {"text": "likes finserv"})()]})()

        return type("R", (), {"memories": [_Entry()]})()

    async def add_session_to_memory(self, session):
        self.stored += 1


def test_recall_is_scoped_to_the_verified_subject_only():
    fake = _FakeMem()
    memories = asyncio.run(memory.recall(fake, _identity("alice"), "what do I work on"))
    assert memories == ["likes finserv"]
    # The only user_id ever queried is the caller's own verified subject.
    assert fake.searched_user_ids == ["alice"]


def test_guest_recall_and_store_are_no_ops():
    fake = _FakeMem()
    guest = _identity("guest:abc", guest=True)
    assert asyncio.run(memory.recall(fake, guest, "q")) == []
    asyncio.run(memory.remember(fake, guest, session=object()))
    assert fake.searched_user_ids == [] and fake.stored == 0  # guests never touch memory


def test_unconfigured_deployment_recalls_and_stores_nothing():
    assert asyncio.run(memory.recall(None, _identity("alice"), "q")) == []
    asyncio.run(memory.remember(None, _identity("alice"), session=object()))  # no error


def test_list_memories_is_scoped_and_drops_other_users(monkeypatch):
    # Unconfigured -> nothing; guest -> nothing even when configured.
    monkeypatch.delenv("BRAIN_AGENT_ENGINE", raising=False)
    assert memory.list_memories(_identity("alice")) == []
    monkeypatch.setenv("BRAIN_AGENT_ENGINE", "projects/p/locations/l/reasoningEngines/1")
    assert memory.list_memories(_identity("g", guest=True)) == []

    # Configured + signed-in: only the caller's own facts. Even if the backend returned
    # another user's, the client-side scope check drops it (defense in depth).
    class _Mem:
        def __init__(self, uid, fact):
            self.scope = {"user_id": uid}
            self.fact = fact

    class _Memories:
        def list(self, *, name, config=None):
            return iter([_Mem("alice", "likes white"), _Mem("bob", "secret")])

    class _AgentEngines:
        memories = _Memories()

    class _Client:
        def __init__(self, **kw):
            self.agent_engines = _AgentEngines()

    import vertexai

    monkeypatch.setattr(vertexai, "Client", _Client)
    assert memory.list_memories(_identity("alice")) == ["likes white"]


def test_format_recall_is_empty_without_memories():
    assert memory.format_recall([]) == ""
    assert "likes finserv" in memory.format_recall(["likes finserv"])
