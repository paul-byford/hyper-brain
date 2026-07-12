---
type: Reference
title: Candidate data privacy and consent
domain: enterprise-ai-recruitment
tags: [privacy, consent, data-protection]
---

# Candidate data privacy and consent

Recruiting runs on some of the most sensitive personal data an enterprise holds:
CVs, contact details, work history, and sometimes assessment results. Handling it
lawfully is foundational, not optional.

## Principles that apply

- **Lawful basis and consent.** Be clear about why data is collected and for how
  long it is kept, and honour candidate consent, including for talent pools where
  a candidate is retained for future roles.
- **Purpose limitation and minimisation.** Use candidate data only for the role it
  was provided for, and collect only what the assessment needs.
- **Transparency and rights.** Under regimes such as GDPR, candidates can ask what
  is held about them and object to purely automated decisions with significant
  effect.

## Engineering implications

Isolate candidate data by purpose, keep retention timers on it, and log access.
The matching signal in [[AI sourcing and candidate matching]] should draw only on
data the candidate provided for hiring, and the records kept for
[[Bias audits and hiring compliance]] must themselves respect these limits. Copilot
notes from [[Structured interview copilots]] are candidate data too and inherit the
same controls.
