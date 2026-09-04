"""Parsing and validation of LLM model responses into reports.

This module turns a parsed JSON response body into
a `CaseReport` or a typed failure, with no knowledge of HTTP, retries, or
timeouts. `client.py` depends on this module; the dependency runs one way,
so no cycle is possible.
"""

import re
from typing import Any

from pydantic import ValidationError

from .models import CaseReport, LlmReportSchema, ReportMetadata
from .prompt import CONTEXT, PROMPT_VERSION
from .provider import ProviderConfig
from .util import collapse_for_log


class LlmResponseError(Exception):
    """Raised when a chat-completion response cannot be turned into a report.

    Args:
        fallback_reason: Stable reason identifying the failure, used to
            populate :class:`~reporting.client.GenerationResult`.
        detail: What specifically went wrong, for logging only (never sent
            to the API caller). For example, when ``fallback_reason`` is
            ``"llm-invalid-json"`` because the provider's JSON is missing a
            required field, ``detail`` is the pydantic ``ValidationError``
            text (collapsed to one line via ``collapse_for_log``) plus the
            raw content that failed, e.g.::

                ValidationError: 3 validation errors for LlmReportSchema summary Field required [type=missing, input_value={}, input_type=dict] ... | content={}

            Several distinct problems can share one ``fallback_reason``;
            ``detail`` is what tells them apart in the logs.
    """

    def __init__(self, fallback_reason: str, detail: str | None = None) -> None:
        super().__init__(fallback_reason)
        self.fallback_reason = fallback_reason
        self.detail = detail


class LlmResponseParser:
    """Extracts and validates the LLM's response from chat-completion responses.

    Expected input format:
        This parser assumes the OpenAI-compatible chat-completion response
        schema. Every provider this parser is exposed to (Mistral direct,
        OpenRouter) conforms to this schema, which is what allows a single
        implementation to handle both without provider-specific branches::

            {
              "choices": [
                {
                  "finish_reason": "stop",
                  "message": {
                    "role": "assistant",
                    "content": "{...json body produced by the model...}",
                    "refusal": null
                  }
                }
              ]
            }

        No field in this schema is assumed to be present or well-formed at
        runtime. A network fault, a non-conforming provider, or a malformed
        intermediary (e.g. a proxy) can produce a response that deviates
        from it. Accordingly, every field is validated defensively, and any
        deviation is surfaced as a typed :class:`LlmResponseError`.

    Field semantics:
        ``choices`` is a list because the underlying API supports requesting
        multiple candidate completions per prompt via the request-level
        ``n`` parameter. This parser always requests a single completion and
        therefore only ever reads ``choices[0]``; the index access is
        nonetheless validated defensively, as provider conformance is not
        guaranteed.

        ``finish_reason`` indicates how generation terminated, which cannot
        be inferred from ``content`` alone:

        - ``"stop"``: generation completed normally; ``content`` is safe to
          parse as JSON.
        - ``"length"``: generation was truncated at the maximum output
          token limit; ``content`` is incomplete and must not be parsed.
        - ``"content_filter"``: the provider's safety filter withheld the
          output.
        - ``"tool_calls"``: the model elected to invoke a function. Not
          applicable here, as this parser only ever requests plain JSON
          content.

        ``message.refusal`` is a dedicated field (as opposed to a refusal
        expressed as prose within ``content``) so that a refusal is
        structurally distinguishable from a valid answer, rather than
        requiring text-pattern matching. It is checked prior to ``content``
        because it is the more authoritative signal.

        ``message`` is nested within ``choice``, mirroring the shape of a
        request's ``messages`` entries (``{role, content}``), so that a
        response message can be appended directly to a subsequent request's
        ``messages`` array for multi-turn exchanges.
    """

    def parse_llm_response(self, response_json: dict[str, Any]) -> LlmReportSchema:
        """Turn a parsed chat-completion body into a validated report response.

        Walks ``choices[0]`` once. For this parser, ``choices`` is always a
        single-element list (see the class docstring), so the first element
        is the only element.

        This method raises :class:`LlmResponseError` on the first check
        below that fails. Checks run in this order:

        1. ``response_json["choices"]`` is a list and is non-empty.
           Failure raises ``llm-empty-response``.
        2. ``choices[0]`` is a dict. Failure raises ``llm-empty-response``.
        3. ``finish_reason`` is not ``"length"``. Failure raises
           ``llm-output-truncated``.
        4. ``finish_reason`` is not ``"content_filter"``. Failure raises
           ``llm-content-filtered``.
        5. ``message.refusal`` is falsy. Failure raises ``llm-refusal``.
        6. ``message.content`` is a non-blank string. Failure raises
           ``llm-empty-response``.

        Only once all six checks pass does it attempt to parse and
        validate ``content`` as JSON; a failure there raises
        ``llm-invalid-json``.
        """

        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmResponseError("llm-empty-response", f"choices={collapse_for_log(repr(choices))}")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LlmResponseError("llm-empty-response", f"choice={collapse_for_log(repr(first_choice))}")

        finish_reason = first_choice.get("finish_reason")
        if finish_reason == "length":
            raise LlmResponseError(
                "llm-output-truncated", "finish_reason=length; raise DEFAULT_MAX_OUTPUT_TOKENS in client.py"
            )
        if finish_reason == "content_filter":
            raise LlmResponseError("llm-content-filtered", "finish_reason=content_filter")

        message = first_choice.get("message")
        if isinstance(message, dict) and message.get("refusal"):
            raise LlmResponseError("llm-refusal", f"refusal={collapse_for_log(str(message['refusal']))}")

        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LlmResponseError("llm-empty-response", detail=f"choice={collapse_for_log(repr(first_choice))}")

        try:
            return LlmReportSchema.model_validate_json(normalise_json_content(content))
        except (ValidationError, ValueError) as exc:
            raise LlmResponseError(
                "llm-invalid-json",
                detail=(
                    f"{type(exc).__name__}: {collapse_for_log(str(exc))} "
                    f"| content={collapse_for_log(content)}"
                ),
            ) from exc


def normalise_json_content(content: str) -> str:
    """Strip a markdown code fence around ``content``, if present.

    Models routinely wrap JSON output in a ```` ```json ... ``` ```` fence
    even when the prompt asks for raw JSON, which would otherwise fail
    ``model_validate_json``. Only that outer wrapping is corrected: the
    fence regex is matched with ``re.fullmatch`` rather than
    ``re.search``, so it only fires when the fence markers open and close
    the *entire* string with nothing outside them. If triple backticks
    show up elsewhere instead — say, inside a field value like
    ``{"note": "wrap code in ```like this```"}``, which has JSON content
    before the first triple-backtick and after the second — ``fullmatch``
    fails and nothing is stripped, so the string is returned as-is.

    Args:
        content: The raw model output, with or without a surrounding
            fence.

    Returns:
        The fenced body if ``content`` is a single ```` ... ```` or
        ```` JSON ```` fenced block (case-insensitive), otherwise
        ``content`` stripped of leading/trailing whitespace.
    """

    stripped = content.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return fence_match.group(1).strip() if fence_match else stripped


def make_report_from_llm_response(
    llm_report_schema: LlmReportSchema,
    *,
    provider: ProviderConfig,
    latency_ms: int,
) -> CaseReport:
    """Convert validated LLM JSON (the LlmReportSchema instance) into the public report."""

    return CaseReport(
        summary=llm_report_schema.summary,
        observations=llm_report_schema.observations,
        qualityChecks=llm_report_schema.quality_checks,
        reportMetadata=ReportMetadata(
            mode="llm",
            model=provider.model,
            provider=provider.provider,
            promptVersion=PROMPT_VERSION,
            latencyMs=latency_ms,
            context=CONTEXT,
        ),
    )
