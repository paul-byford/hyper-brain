---
type: Index
title: AI engineering for financial services, overview
domain: finserv-ai-engineering
tags: [overview, index]
---

# AI engineering for financial services

This domain collects cutting-edge, practical patterns for building AI systems
inside banks and capital-markets firms, where the constraints are as important as
the capabilities: sensitive data, model risk governance, auditability, and latency.

## Where to start

- Retrieval over regulated content: [[Retrieval-augmented generation for trade surveillance]].
- Governing the models themselves: [[Model risk governance for LLMs]].
- Real-time paths: [[Real-time fraud detection with streaming features]].
- Keeping data in the tenancy: [[In-tenancy vector search and embeddings]].

## The through-line

Every pattern here assumes the same non-negotiables: content does not leave the
bank's cloud tenancy, every model output is traceable to its inputs, and a human
reviewer can reconstruct why a decision was made. The engineering is shaped by
those constraints, not bolted onto them afterwards.
