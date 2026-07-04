---
title: Feature stores for real-time ML in banking
domain: finserv-ai-engineering
tags:
- features
- streaming
- latency
source: raw-finserv
source_url: raw/finserv/feature-stores-for-realtime-ml.md
fetched_at: '2026-07-03T12:32:05+00:00'
checksum: b8929b1e0f4880c99ea3f7bd192439c2b39ebcbff6b2bc1b4bb59b161a83cbc2
ingest_run: ingest-b13e3f7b6873
---

# Feature stores for real-time ML in banking

A feature store is the shared substrate that lets the same engineered signals
serve both model training and low-latency inference. In banking it earns its keep
by removing training/serving skew: the aggregate a model learned on is computed
the same way when it scores a live transaction.

## Online and offline paths

The offline store holds historical features for training and backtests; the online
store holds the freshest values for serving, keyed for single-digit-millisecond
reads. The same feature definition materialises to both, so a fraud model trained
offline sees identical semantics online. This is the backbone under
[[realtime-fraud-detection]], where the scoring path has no time to recompute
history.

## Freshness and point-in-time correctness

Streaming aggregates (transaction velocity, first-seen device, sudden geography)
must be joined point-in-time, using only what was known at decision time, or the
model learns from the future and fails silently in production. Feature stores make
this join a property of the platform rather than a thing each team re-implements.

## Keeping features in-tenancy

Feature values derived from sensitive data are themselves sensitive. Computing and
serving them inside the tenancy, next to [[in-tenancy-vector-search]], keeps the
whole retrieval-and-scoring path inside the same trust and region boundary rather
than exporting engineered signals to a third party.
