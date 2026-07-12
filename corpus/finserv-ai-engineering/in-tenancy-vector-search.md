---
type: Reference
title: In-tenancy vector search and embeddings
domain: finserv-ai-engineering
tags: [embeddings, vector-search, data-boundary]
---

# In-tenancy vector search and embeddings

The single biggest question a bank security reviewer asks about a retrieval system
is: where does our content go to be embedded, and where does the index live? The
defensible answer keeps both inside the bank's own cloud tenancy and region.

## Embeddings without leaving the tenancy

Use the cloud provider's first-party embedding model, called from inside the same
tenancy, rather than a third-party embeddings API. Content transits to a managed
model under the same contractual and network controls as the rest of the estate,
and is not used to train anyone's model. For the strictest cases, a self-hosted
embedding model behind the same interface removes even that transit.

## Where the index rests

At small and medium corpus sizes, a vector index does not need a running database.
An index artefact in the tenancy's own object storage, loaded into a scale-to-zero
service, is cheaper and has a smaller attack surface than a standing database. As
the corpus grows, an approximate-nearest-neighbour index or a managed vector
service takes over without changing the data boundary.

## Why this matters across the domain

This pattern underpins [[Retrieval-augmented generation for trade surveillance]]
and is a control referenced by [[Model risk governance for LLMs]]. The data
boundary is a design input, not an afterthought.
