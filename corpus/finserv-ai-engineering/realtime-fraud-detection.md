---
type: Reference
title: Real-time fraud detection with streaming features
domain: finserv-ai-engineering
tags: [fraud, streaming, latency]
---

# Real-time fraud detection with streaming features

Card and payment fraud decisions happen in tens of milliseconds, inside the
authorisation flow. That latency budget shapes the whole architecture: heavy
models and slow lookups are out; precomputed features and fast scoring are in.

## Feature freshness

The signal that catches fraud is often very recent: velocity of transactions,
sudden geography changes, a device seen for the first time. A streaming feature
pipeline maintains these aggregates in near real time so the scoring model sees
fresh state, not last night's batch.

## Model choices

Gradient-boosted trees still win many fraud problems on latency and
interpretability. Where deep models help, they run as compact, distilled versions
behind a strict timeout, with a rules fallback. The point is a predictable tail
latency, not the fanciest model.

## Governance and drift

Fraud patterns move adversarially, so drift is the norm. Monitor score
distributions and precision at the operating threshold, and retrain on a schedule.
This ties back to [[Model risk governance for LLMs]]: the governance discipline is
the same even though the model type differs. Keep the feature store and scoring
inside the tenancy, consistent with [[In-tenancy vector search and embeddings]].
