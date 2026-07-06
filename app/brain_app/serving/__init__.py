"""The serving layer: the MCP tool surface and the write path's review gate.

``BrainService`` (service.py) holds the tool logic and enforces the domain ACL and
write scope, so it is fully testable with no MCP client and no cloud. ``server.py``
is a thin MCP-over-streamable-HTTP binding around it. The write path lands
proposals through a review gate (proposals.py), never as a live write to main.
"""

from __future__ import annotations

from .proposals import (
    GcsCorpusGate,
    GcsProposalGate,
    GitBranchGate,
    MemoryGate,
    Proposal,
    ProposalResult,
    ReviewGate,
    get_gate,
)
from .service import (
    AccessError,
    BrainService,
    DocumentNotFound,
    DomainNotAuthorized,
    WriteScopeError,
)

__all__ = [
    "AccessError",
    "BrainService",
    "DocumentNotFound",
    "DomainNotAuthorized",
    "GcsCorpusGate",
    "GcsProposalGate",
    "GitBranchGate",
    "MemoryGate",
    "Proposal",
    "ProposalResult",
    "ReviewGate",
    "WriteScopeError",
    "get_gate",
]
