---
title: Model risk governance for LLMs
domain: finserv-ai-engineering
tags: [governance, model-risk, sr11-7]
---

# Model risk governance for LLMs

Banks already have a model risk management discipline, shaped in the US by
supervisory guidance SR 11-7: models must be documented, independently validated,
and monitored, with clear ownership. Large language models do not escape this;
they stretch it.

## What changes with LLMs

- **Non-determinism.** The same prompt can yield different outputs, so validation
  moves from exact reproduction to distributional and behavioural testing.
- **Emergent scope.** A general model can be used for tasks it was never validated
  for. Governance must pin down the specific use, not the model in the abstract.
- **Data lineage.** With retrieval in the loop, the effective inputs include the
  retrieved context. Lineage has to cover the corpus, not just the prompt.

## Controls that work

Treat each use case as the unit of governance. Document the intended use, the
retrieval corpus, the evaluation set, and the monitoring plan. Require grounded,
cited outputs where a wrong answer has regulatory consequence, as in
[[Retrieval-augmented generation for trade surveillance]]. Keep an audit trail
that ties every output to its prompt, retrieved context, and model version.

## Monitoring

Continuously evaluate for hallucination and drift on a held-out set, and alert on
degradation. This is the same idea as offline model monitoring, applied to a
probabilistic system, and it connects directly to
[[Real-time fraud detection with streaming features]] where drift shows up fast.
