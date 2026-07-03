# Agent evals (free, offline tier)

ADK's built-in eval framework, run in CI via `AgentEvaluator` with deterministic
metrics and no paid service (ARCHITECTURE.md section 10):

- `tool_trajectory_avg_score` (1.0): the agent must call the right tool with the
  right arguments.
- `response_match_score` (ROUGE, 0.7): the final answer must match the reference.

The agent runs offline here (a deterministic `FakeBrainModel` plus the brain tools
bound in-process against a domain-scoped `BrainService`), so these run free and
reproducibly on every pull request. `test_config.json` holds the thresholds and is
shared by every `*.test.json` in this folder.

Files are in ADK's `EvalSet` schema, which both `adk eval` (CLI) and the pytest
`AgentEvaluator` load identically:

- `golden.evalset.json` - a caller scoped to `finserv-ai-engineering` asks in-domain
  questions; the agent searches and answers from that domain.
- `isolation.evalset.json` - the **isolation eval**. The same finserv-scoped caller
  asks a recruitment question. The agent must still only surface
  `finserv-ai-engineering` material: the reference names that domain and no other,
  so any leak of `enterprise-ai-recruitment` content fails the build. The domain
  boundary is asserted by the eval suite, not just in prose.

Run them with either:

    python -m pytest app/tests -q -m eval
    adk eval app/brain_app/agent app/brain_app/agent/evals/golden.evalset.json \
        --config_file_path app/brain_app/agent/evals/test_config.json

The reference strings summarise results by domain rather than echoing ranked hit
text, so they stay valid across corpus edits while still failing on any
cross-domain leak. The richer, paid LLM-judged metrics
(`final_response_match_v2`, `hallucinations_v1`, `safety_v1`) are a
controlled-profile opt-in and are not run in the free tier.
