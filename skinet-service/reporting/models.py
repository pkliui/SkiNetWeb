"""Pydantic request and response models and shared domain constants for case reports."""

from types import MappingProxyType
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

ReportMode = Literal["llm", "deterministic-fallback"]
ReportProviderName = Literal["mistral", "openrouter", "local"]

ReportItem = Annotated[str, Field(min_length=1, max_length=240)]


class ApiModel(BaseModel):
    """Base model that accepts Python snake_case and API camelCase aliases."""

    # Every subclass field carries a camelCase `alias` so the JS frontend can
    # send/receive camelCase JSON (e.g. CaseMetrics.pred_area_pct <-> "predAreaPct").
    # Pydantic v2 accepts only the alias by default, rejecting the snake_case name
    # from both incoming JSON and Model(x=...) kwargs — even in Python code.
    # populate_by_name=True accepts both, so JSON keeps using the alias while
    # tests and in-process code can construct these models with plain snake_case kwargs.
    model_config = ConfigDict(populate_by_name=True)


class CaseMetrics(ApiModel):
    """Segmentation metrics supplied by the UI after mask generation.

    Computed client-side in the browser (``computeMetrics`` in
    ``ResultsGrid.tsx``) from the predicted and ground-truth mask pixels,
    then sent as-is via ``useCaseReport.ts``'s :func:`requestCaseReport`
    (POST to ``/api/case-report``, proxied to this endpoint) as
    :attr:`CaseReportRequest.metrics`.
    The backend never receives the raw masks and cannot recompute or verify
    these values (see :data:`prompt.CONTEXT`).

    Consumed on both report paths: :func:`quality.classify` reads these
    fields to bucket them into agreement bands and quality caveats;
    :class:`ReportPromptBuilder` (``prompt.py``) includes them in the LLM
    prompt; :class:`DeterministicReportBuilder` (``fallback.py``) reads them
    directly to assemble the templated report.
    """

    pred_area_pct: float = Field(
        ..., alias="predAreaPct", ge=0, le=100, description="Percentage of the image covered by the predicted lesion mask."
    )
    dice: float | None = Field(
        default=None, ge=0, le=1, description="Dice coefficient between predicted and ground-truth masks, if a ground-truth mask was supplied."
    )
    iou: float | None = Field(
        default=None, ge=0, le=1, description="Intersection-over-union between predicted and ground-truth masks, if a ground-truth mask was supplied."
    )
    sensitivity: float | None = Field(
        default=None, ge=0, le=1, description="True positive rate of the predicted mask against the ground-truth mask, if supplied."
    )
    specificity: float | None = Field(
        default=None, ge=0, le=1, description="True negative rate of the predicted mask against the ground-truth mask, if supplied."
    )


class CaseReportRequest(ApiModel):
    """Input contract for generating a segmentation report.

    Handed to :meth:`CaseReportGenerator.generate`, which routes it to
    :meth:`ReportPromptBuilder.build_user_prompt` (LLM path) or
    :class:`DeterministicReportBuilder` (fallback path) depending on
    whether the LLM call succeeds.
    """

    file_name: str | None = Field(
        default=None, alias="fileName", max_length=180, description="Original name of the uploaded image file."
    )
    metrics: CaseMetrics | None = Field(default=None, description="Segmentation metrics for this case, if computed.")


class ReportMetadata(ApiModel):
    """Metadata on how a :class:`CaseReport` was generated.

    On the LLM path (``mode="llm"``), ``model``/``provider`` name the
    answering provider and ``latency_ms`` times that call; ``fallback_reason``
    is unset. On the fallback path (``mode="deterministic-fallback"``),
    ``model``/``provider`` are fixed to ``"local-template"``/``"local"`` and
    ``fallback_reason`` records why the LLM path was abandoned (e.g.
    ``"llm-not-configured"``, ``"llm-invalid-response"``).

    ``prompt_version`` is a hash of the prompt text
    (:data:`prompt.SYSTEM_PROMPT` + ``REPORT_REQUIREMENTS`` + ``CONTEXT``),
    so it updates automatically when the prompt changes. ``context`` echoes
    the :data:`prompt.CONTEXT` caveats supplied to the model or template.

    Constructed only in :func:`response_parser.make_report_from_llm_response`
    (LLM path) and :meth:`DeterministicReportBuilder.build` (fallback path).
    """

    mode: ReportMode = Field(description='Which code path produced the report: "llm" or "deterministic-fallback".')
    model: str = Field(description='Model that answered, or "local-template" on the fallback path.')
    provider: ReportProviderName = Field(description='Provider that answered, or "local" on the fallback path.')
    prompt_version: str = Field(
        alias="promptVersion", description="Hash of the prompt template in effect when this report was generated."
    )
    latency_ms: int = Field(
        alias="latencyMs", description="Wall-clock duration of the LLM call, or of the failed attempt on the fallback path."
    )
    context: list[str] = Field(description="Caveats from prompt.CONTEXT supplied to the model or template.")
    fallback_reason: str | None = Field(
        default=None,
        alias="fallbackReason",
        description="Reason slug for why the LLM path was abandoned; unset on the LLM path.",
    )


class ReportContentFields(BaseModel):
    """Report content fields shared by :class:`CaseReport` and :class:`LlmReportSchema`.

    Deliberately a bare ``BaseModel`` with no ``model_config``: each
    subclass needs an incompatible config (``LlmReportSchema`` rejects
    snake_case/extra keys; ``CaseReport`` accepts both via ``ApiModel``),
    and Pydantic resolves ``model_config`` per subclass from its own MRO.
    """

    summary: str = Field(min_length=1, max_length=600, description="Summary in one or two sentences describing the supplied metrics.")
    observations: list[ReportItem] = Field(
        min_length=1, max_length=6, description="Concrete observations from the segmentation output."
    )
    quality_checks: list[ReportItem] = Field(
        alias="qualityChecks",
        min_length=1,
        max_length=6,
        description="Possible engineering quality checks or failure modes to inspect.",
    )


class CaseReport(ApiModel, ReportContentFields):
    """API response shown in the case-report panel, returned by ``POST /case-report``.

    Built by :meth:`CaseReportGenerator.generate` from either the LLM path
    (:func:`response_parser.make_report_from_llm_response`) or the fallback
    path (:meth:`DeterministicReportBuilder.build`) — same type either way.
    ``summary``/``observations``/``quality_checks`` mirror the contract
    validated by :class:`LlmReportSchema`; ``report_metadata`` is attached
    afterward by whichever path produced the report.
    """

    report_metadata: ReportMetadata = Field(alias="reportMetadata")


class LlmReportSchema(ReportContentFields):
    """Fields required from the LLM response — the source of truth for the response shape.

    The prompt's outputContract (``REPORT_JSON_SCHEMA`` in prompt.py) is
    generated from these fields, so the two can't drift apart. Extra keys,
    missing keys, empty lists, and snake_case key spellings are all
    rejected: an off-contract response fails validation and triggers the
    deterministic fallback instead of being silently patched up.

    Constructed only in :meth:`LlmResponseParser.parse_llm_response`, by
    validating the LLM's raw JSON reply. Never returned from the API
    directly — :func:`response_parser.make_report_from_llm_response`
    converts a validated instance into a :class:`CaseReport` first.
    """

    model_config = ConfigDict(extra="forbid")


def _build_report_json_schema() -> dict[str, Any]:
    """Derive the report contract from :class:`LlmReportSchema`.

    Pydantic's JSON Schema carries every constraint the validator enforces,
    so neither the prompt's ``outputContract`` nor the provider's
    structured-output request can advertise a shape the response model
    would reject. Strips only what is developer-facing: the class
    docstring and the auto-generated field titles.

    Defined here, beside the model it is derived from, rather than in
    ``prompt.py``: both ``prompt.py`` and ``provider.py`` need it, and
    ``provider.py`` cannot import from ``prompt.py`` without creating an
    import cycle (``prompt.py`` imports ``ProviderConfig``).

    Shape (fields alphabetized by Pydantic; `properties[<key>]` is what
    ``prompt.py``'s ``_field_schema`` indexes into)::

        {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "observations", "qualityChecks"],
            "properties": {
                "summary": {"type": "string", "minLength": 1, "maxLength": 600, "description": "..."},
                "observations": {
                    "type": "array", "minItems": 1, "maxItems": 6,
                    "items": {"type": "string", "minLength": 1, "maxLength": 240},
                    "description": "...",
                },
                "qualityChecks": {  # alias of quality_checks
                    "type": "array", "minItems": 1, "maxItems": 6,
                    "items": {"type": "string", "minLength": 1, "maxLength": 240},
                    "description": "...",
                },
            },
        }

    Returns:
        A JSON Schema dict describing the report contract, with the class
        docstring and field titles removed.
    """

    schema = LlmReportSchema.model_json_schema(by_alias=True)
    schema.pop("description", None)
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


REPORT_JSON_SCHEMA = _build_report_json_schema()
"""dict[str, Any]: JSON Schema for :class:`LlmReportSchema`, the LLM's expected output shape.

Used in two places, both referencing this same object:
1. As the `response_format` sent to the provider, via
   :data:`STRICT_JSON_SCHEMA_RESPONSE_FORMAT` below. When the resolver's
   `structured_outputs` constant (see `provider.py`) is `True`, the provider
   uses this to actually constrain what tokens the model can generate.
2. As the `outputContract` field inside the prompt text itself
   (`ReportPromptBuilder.build_user_prompt`), where it's just read by the
   model as an instruction and enforces nothing on its own.
"""

REPORT_SCHEMA_NAME = "case_report"

JSON_OBJECT_RESPONSE_FORMAT: Mapping[str, Any] = MappingProxyType({"type": "json_object"})
"""Mapping[str, Any]: Weak response-format contract.
Guarantees syntactically valid JSON; makes no guarantee about keys.
"""

STRICT_JSON_SCHEMA_RESPONSE_FORMAT: Mapping[str, Any] = MappingProxyType(
    {
        "type": "json_schema",
        "json_schema": {
            "name": REPORT_SCHEMA_NAME,
            "strict": True,
            "schema": REPORT_JSON_SCHEMA,
        },
    }
)
"""Mapping[str, Any]: Strong response-format contract.

Requests constrained decoding, which restricts the model's token sampler so
that only JSON matching the schema's keys and types can be generated.
Providers' strict
implementations generally stop at that key/type structure and ignore
``maxLength``, ``minItems``, and ``maxItems``, so :class:`LlmReportSchema`
remains the sole enforcer of length and item-count bounds; this is an added
layer on top of the response-side validation.

Support is model-dependent: providers without strict-schema support may
error or silently fall back to best-effort JSON, so this is opt-in per
provider (see ``EnvironmentProviderResolver``).
"""

EXAMPLE_OUTPUT = {
    "summary": "Segmentation completed for image _NAME_OF_IMAGE using SkiNet segmentation model"
    "trained on ISIC 2017 dataset. Predicted segmentation mask is shown in _GREEN. If user provided an ISIC 2017 test image"
    "available in EXAMPLES column, ground truth mask is shown in RED. If user uploaded a photo, no ground truth is available."
    "The result shows an HIGH or GOOD or POOR precision in of boundary delineation, especially in the segmentation of atypical boundaries"
    " as well as in more complicated morphology patterns.",
    "observations": [
        "Dice coefficient of 0.91 and IoU score of 0.89 indicate STRONG or MODERATE or WEAK agreement between predicted and ground-truth masks.",
        "Predicted area (8.2%) is consistent with a single, well-bounded lesion region.",
    ],
    "qualityChecks": [
        "Review boundary pixels near low-contrast edges, since Dice does not measure boundary fidelity.",
        "Confirm ground-truth mask alignment if sensitivity and specificity diverge sharply.",
    ],
}


class ProviderStatus(ApiModel):
    """Live readiness of the configured LLM provider, for on-demand monitoring."""

    llm_configured: bool = Field(alias="llmConfigured", description="Whether an LLM provider is configured at all.")
    reachable: bool = Field(description="Whether the configured provider responded to a live reachability check.")
    reason: str | None = Field(default=None, description="Explanation when not reachable or not configured.")
