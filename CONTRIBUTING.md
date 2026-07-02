# Contributing to hyper-brain

Two kinds of change live in this repository, and both go through review:

1. **Code** (the retrieval core, serving, agent, UI, infrastructure).
2. **Knowledge** (the markdown corpus). Knowledge is a reviewable, versioned
   asset: adding or changing what the brain knows is a pull request, inspectable
   in review and revertible with `git revert`.

## Changing the corpus

- Corpus lives under `corpus/<domain>/`. Each domain is an isolation boundary; a
  document belongs to exactly one domain.
- Every document begins with frontmatter:

  ```markdown
  ---
  title: Retrieval-augmented generation for trade surveillance
  domain: finserv-ai-engineering
  tags: [rag, surveillance]
  ---
  ```

- Link related documents **within the same domain** with `[[wikilinks]]` using the
  target document's title or file stem. Cross-domain links are intentionally not
  followed by retrieval, because domains are isolated.
- After changing the corpus, run `make index` and `make test` so the index builds
  and the retrieval and isolation tests still pass.

## Changing code

- Set up: `make install` creates a virtualenv under `.venv` and installs the app
  with dev tools.
- Before opening a PR: `make lint` and `make test` must pass. CI runs the same,
  plus the security and eval pillars.
- Match the style of the surrounding code. Formatting and linting are enforced by
  `ruff`.

## The three testing pillars

A change is not done until the relevant pillar passes (`ARCHITECTURE.md` section
10):

- **Functional:** `make test` (unit and integration tests).
- **Security:** isolation and token-verification tests, `bandit`, `pip-audit`,
  `gitleaks`, and infrastructure policy-as-code. Anything touching `auth/`,
  `config/` or `infra/` should add or update a security test.
- **AI evals:** changes to retrieval or the agent should be reflected in the eval
  sets so quality regressions are caught.

## Commit and PR conventions

- Small, focused commits with clear messages.
- Fill in the pull request template. Call out anything that touches the data
  boundary, the isolation boundary, or the two-profile switch.
