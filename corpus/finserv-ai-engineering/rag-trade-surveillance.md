---
title: Retrieval-augmented generation for trade surveillance
domain: finserv-ai-engineering
tags: [rag, surveillance, compliance]
---

# Retrieval-augmented generation for trade surveillance

Trade surveillance teams drown in alerts: communications, order data, and market
context that an analyst must correlate to decide whether an alert is worth
escalating. Retrieval-augmented generation helps by grounding a model in the
firm's own policies, past case dispositions, and the specific evidence for an
alert, rather than relying on the model's parametric memory.

## Pattern

Index the surveillance policy library, historical case notes, and regulatory
guidance as chunked markdown. For a given alert, retrieve the most relevant
policy clauses and similar prior cases, then ask the model to draft a rationale
that cites them. The analyst reviews and edits; the citations make the draft
checkable rather than a black box.

## Why grounding matters here

An ungrounded model will confidently invent a policy reference. In surveillance
that is not a curiosity, it is a compliance failure. Grounding every claim in a
retrieved, cited source is what makes the output defensible. See
[[Model risk governance for LLMs]] for how this is documented and controlled, and
[[In-tenancy vector search and embeddings]] for keeping the index inside the
tenancy.

## Evaluation

Measure retrieval precision and recall against a labelled set of alerts with known
relevant policies, and measure how often the drafted rationale's citations are
actually supported by the retrieved text. Groundedness is the metric that matters,
not fluency.
