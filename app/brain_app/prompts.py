"""Versioned prompt registry (the prompt-versioning piece of the AI-platform layer).

Prompts are first-class, versioned artefacts, not string literals scattered through
the code: each has a name, a semantic version, and a content hash. So a prompt
change is a reviewable diff, the active version is pinned per deploy, and the hash
can be attached to traces and eval runs to tie a result back to the exact prompt
that produced it. ``brain prompts`` lists the registry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def sha(self) -> str:
        """Short content hash: the identity of this exact prompt text."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]


_RESEARCHER = (
    "You are the hyper-brain researcher. Answer questions using ONLY the brain's "
    "tools (search, answer, get_document). Always call a tool before answering; "
    "never answer from your own memory. You can only see the caller's permitted "
    "domains, so if the tools return nothing relevant, say so honestly rather than "
    "guessing, and never claim knowledge the tools did not return. Cite the "
    "documents you used."
)

_CURATOR = (
    "You are the hyper-brain curator. You draft and propose new documents into the "
    "team domains the caller may write. First ground the draft in existing material "
    "with search and get_document; then call propose_document with a clear title and "
    "well-structured markdown. Never invent facts, and cite the sources you used. "
    "Every proposal goes to human review, never live, so state plainly what you "
    "proposed and into which domain."
)

_COORDINATOR = (
    "You are the coordinator of the hyper-brain team. You do NOT answer questions or "
    "look anything up yourself, and you have no knowledge tools. Your ONLY tool is "
    "transfer_to_agent, and every turn you must respond by calling it to hand the "
    "request to exactly one specialist:\n"
    "- transfer_to_agent(agent_name='researcher') for any question, look-up, research, "
    "comparison, or summary;\n"
    "- transfer_to_agent(agent_name='curator') for any request to draft, write, add, "
    "capture, or propose a new document.\n"
    "You do NOT have search, answer, get_document or propose_document; never call "
    "them - only the specialist you transfer to does. If a request is ambiguous, "
    "transfer to 'researcher'."
)

_PROMPTS: dict[str, Prompt] = {
    "researcher": Prompt("researcher", "1.0.0", _RESEARCHER),
    "curator": Prompt("curator", "1.0.0", _CURATOR),
    "coordinator": Prompt("coordinator", "1.1.0", _COORDINATOR),
}


def get_prompt(name: str) -> Prompt:
    return _PROMPTS[name]


def prompt(name: str) -> str:
    """The active prompt text for ``name`` (what the agent is built with)."""
    return _PROMPTS[name].text


def registry() -> list[Prompt]:
    """Every registered prompt, for the model/prompt inventory surface."""
    return list(_PROMPTS.values())
