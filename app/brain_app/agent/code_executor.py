"""Selects the analyst's code sandbox.

Two flavours of Google's server-side Code Execution, chosen by config:

- **Managed Vertex AI Code Interpreter** (``BuiltInCodeExecutor``'s heavier sibling): a
  stateful, package-capable sandbox. Set ``BRAIN_CODE_INTERPRETER`` to a provisioned
  extension resource (``projects/<n>/locations/us-central1/extensions/<id>``) to use it.
  **Caveat:** the Code Interpreter extension is **us-central1-only**, so with this set the
  analyst's Python runs *cross-region* from our europe-west2 stack (see infra/modules/
  code_interpreter and ARCHITECTURE.md section 8).
- **Gemini built-in sandbox** (the default, env unset): Gemini executes the code in its own
  region, so it stays **in-region** with the rest of the tenancy.

adk is imported lazily inside the function so importing this module stays cheap (it is on
``agent_run``'s deferred path, which must not pull adk onto the brain's normal requests).
"""

from __future__ import annotations

import os


def code_executor():
    """The analyst's code executor, per ``BRAIN_CODE_INTERPRETER`` (see module docstring)."""
    resource = os.environ.get("BRAIN_CODE_INTERPRETER")
    if resource:
        from google.adk.code_executors import VertexAiCodeExecutor

        return VertexAiCodeExecutor(resource_name=resource)
    from google.adk.code_executors import BuiltInCodeExecutor

    return BuiltInCodeExecutor()
