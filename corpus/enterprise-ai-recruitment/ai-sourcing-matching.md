---
title: AI sourcing and candidate matching
domain: enterprise-ai-recruitment
tags: [sourcing, matching, ranking]
---

# AI sourcing and candidate matching

The top of the recruiting funnel is a search problem: given a role, find the
people most likely to be a strong, interested fit, from the applicant pool and
from passive candidates. Modern matching uses embeddings of role requirements and
candidate profiles rather than brittle keyword filters.

## Semantic matching

Represent both the job description and each candidate profile as vectors so that
"site reliability engineer" matches a profile describing on-call, incident
response and Kubernetes even without the exact title. This surfaces non-obvious
fits and reduces the keyword gaming that plagues traditional applicant tracking
systems.

## Ranking, carefully

Ranking candidates is where fairness risk concentrates. A model that learns from
past hiring decisions can inherit their biases. Keep the matching signal about
skills and evidence, exclude protected characteristics and their proxies, and
treat the ranking as a shortlist for humans, not a verdict. This is covered in
[[Bias audits and hiring compliance]].

## Keeping a human in the loop

Matching produces a ranked shortlist that a recruiter reviews. The downstream
interview process is supported by [[Structured interview copilots]], and all
candidate data used here is governed by [[Candidate data privacy and consent]].
