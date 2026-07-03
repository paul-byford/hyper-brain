"""A deterministic fake LLM for offline, free agent evals.

The production agent runs Gemini on Vertex (in-tenancy). But agents are
probabilistic, and the plan's eval tier must run free and offline in CI
(ARCHITECTURE.md section 10), so this stands in for the model exactly like
``FakeEmbeddings`` stands in for Vertex embeddings. It implements the ADK
``BaseLlm`` interface with a fixed policy:

1. On the first turn it calls the ``search`` tool with the user's question.
2. Once a tool result is in the history it writes a short final answer that
   quotes that result.

That yields a deterministic tool trajectory and a stable final response, so
``tool_trajectory_avg_score`` and ``response_match_score`` are reproducible with
no model call. It never invents content beyond what the (domain-scoped) tool
returned, which is exactly what keeps the isolation eval honest.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

# The fake answers by naming the domains its (scoped) tool results came from. This
# is deterministic and, unlike echoing ranked hit text, stable across corpus edits,
# so eval reference strings stay valid; it also makes the answer encode the very
# property the isolation eval checks (a finserv caller only ever sees finserv).
_ANSWER_PREFIX = "From your permitted domains, the brain found results in:"
_EMPTY_ANSWER = "I found nothing in your permitted domains for that question."
_DOMAIN_TAG = re.compile(r"\[([a-z0-9-]+)\]")


class FakeBrainModel(BaseLlm):
    model: str = "fake-brain"
    tool_name: str = "search"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents or []
        # Decide by looking only at the last content. If it carries a tool result,
        # this is the answer step; otherwise it is a fresh question to dispatch.
        # (Keying off the last message, rather than the last *user* message, avoids
        # depending on which role the runtime tags a function response with.)
        tool_text = self._tool_result_in(contents[-1]) if contents else None

        if tool_text is None:
            query = self._latest_user_text(contents)
            call = types.FunctionCall(name=self.tool_name, args={"query": query})
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(function_call=call)])
            )
            return

        # The tool has answered: reply by naming the (scoped) domains it drew from.
        domains = sorted(set(_DOMAIN_TAG.findall(tool_text)))
        answer = f"{_ANSWER_PREFIX} {', '.join(domains)}." if domains else _EMPTY_ANSWER
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=answer)]))

    @staticmethod
    def _latest_user_text(contents: list[types.Content]) -> str:
        for content in reversed(contents):
            if content.role == "user":
                for part in content.parts or []:
                    if part.text:
                        return part.text
        return ""

    @staticmethod
    def _tool_result_in(content: types.Content) -> str | None:
        for part in content.parts or []:
            response = getattr(part, "function_response", None)
            if response is not None:
                payload = response.response
                if isinstance(payload, dict):
                    return str(payload.get("result", payload))
                return str(payload)
        return None
