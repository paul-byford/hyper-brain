---
title: Bias audits and hiring compliance
domain: enterprise-ai-recruitment
tags: [bias, compliance, regulation]
---

# Bias audits and hiring compliance

Automated employment decision tools are among the most regulated uses of AI.
Getting the model right technically is not enough; it has to be demonstrably fair
and lawfully deployed, with evidence.

## The regulatory landscape

- **New York City Local Law 144** requires an independent bias audit of automated
  employment decision tools and candidate notification before use.
- **US EEOC** guidance applies existing anti-discrimination law to AI hiring
  tools, including disparate-impact analysis.
- **The EU AI Act** classifies AI used in recruitment and candidate evaluation as
  high risk, bringing obligations for risk management, data governance, human
  oversight and transparency.

## What a bias audit involves

Measure selection rates across protected groups and compute impact ratios, test
the tool on representative data, and document mitigations. The audit is periodic,
not one-off, because models and applicant pools drift.

## Engineering implications

Fairness is a build-time and run-time concern. Exclude protected attributes and
their proxies from the [[AI sourcing and candidate matching]] signal, keep humans
accountable for decisions via [[Structured interview copilots]], and retain the
records an audit needs, consistent with [[Candidate data privacy and consent]].
