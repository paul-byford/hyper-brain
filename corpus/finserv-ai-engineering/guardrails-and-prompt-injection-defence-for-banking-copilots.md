---
title: Guardrails and prompt-injection defence for banking copilots
domain: finserv-ai-engineering
tags:
- guardrails
- security
- llm
source: raw-finserv
source_url: raw/finserv/guardrails-prompt-injection.md
fetched_at: '2026-07-04T18:49:37+00:00'
checksum: 7c79d31185e74711fd46248499828b462a82fd87e96fe356dfdea11f58effcc7
ingest_run: ingest-c666142b7592
---

# Guardrails and prompt-injection defence for banking copilots

A banking copilot that reads retrieved documents is exposed to prompt injection: a
malicious or careless source can carry instructions that try to override the
assistant's rules. In a regulated setting this is a control failure, not a
curiosity, so defence is layered.

## Treat retrieved content as data, not instructions

The model must never execute instructions found in retrieved chunks. Keep the
system prompt authoritative, mark retrieved text as untrusted context, and strip
anything that looks like a directive. This is the same discipline that
[[Retrieval-augmented generation for trade surveillance]] relies on to keep
grounded answers defensible.

## Scope every tool call to the caller's permissions

Injection often aims to make the assistant fetch data the caller may not see. The
brain enforces the domain ACL server-side, so even a successful injection cannot
cross the isolation boundary. Governance and monitoring follow
[[Model risk governance for LLMs]]: log tool calls, watch for anomalous retrieval,
and alert on scope-escape attempts.

## Test it continuously

Adversarial retrieval is an eval, not a one-off review: a poisoned document that
instructs the agent to reveal another domain must fail the build, not ship.
