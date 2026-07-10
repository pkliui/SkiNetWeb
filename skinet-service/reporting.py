"""Grounded LLM reporting for SkiNet segmentation results.

The module turns deterministic segmentation metrics into a structured case report by
combining prompt guardrails, provider-agnostic chat-completion calls, strict
Pydantic validation, retry handling, and a deterministic fallback. It is designed
to demonstrate production-minded LLM integration without making clinical claims.
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

PROMPT_VERSION = "skinet-case-report-v2"
DEFAULT_AZURE_API_VERSION = "2024-02-15-preview"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_OUTPUT_TOKENS = 700

CLINICAL_CONTEXT = [
    "SkiNet produces lesion segmentation masks for dermoscopy images; it does not classify malignancy.",
    "Area, Dice, IoU, sensitivity, and specificity are engineering metrics for model behavior and mask agreement.",
    "Clinical interpretation requires a qualified clinician and additional patient context.",
]

SYSTEM_PROMPT = (
    "You are a careful medical AI product engineer. Explain a dermoscopy segmentation "
    "result for engineering review only. Do not diagnose disease, estimate malignancy, "
    "or invent clinical facts not present in the input."
)

REPORT_JSON_SCHEMA = {
    "summary": "One or two sentences grounded in the supplied metrics.",
    "observations": ["Concrete observations from the segmentation output."],
    "qualityChecks": ["Engineering quality checks or failure modes to inspect."],
}
REPORT_REQUIREMENTS = [
    "Return only valid JSON. Do not wrap the JSON in markdown.",
    "Use the exact keys from outputContract.",
    "Ground every statement in the supplied segmentation metrics and retrieved context.",
    "If ground-truth metrics are absent, say they are unavailable instead of inferring agreement.",
    "Do not provide a diagnosis, malignancy probability, treatment recommendation, or triage decision.",
    "Mention clinician review only as a safety control, not as a clinical judgment.",
]

ReportItem = Annotated[str, Field(min_length=1, max_length=240)]


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), 0.1)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %.1f", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), 0)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %d", name, raw, default)
        return default


class ApiModel(BaseModel):
    """Base model that accepts Python snake_case and API camelCase aliases."""

    model_config = ConfigDict(populate_by_name=True)


class CaseMetrics(ApiModel):
    """Segmentation metrics supplied by the UI after mask generation."""

    pred_area_pct: float = Field(..., alias="predAreaPct", ge=0, le=100)
    dice: float | None = Field(default=None, ge=0, le=1)
    iou: float | None = Field(default=None, ge=0, le=1)
    sensitivity: float | None = Field(default=None, ge=0, le=1)
    specificity: float | None = Field(default=None, ge=0, le=1)


class CaseReportRequest(ApiModel):
    """Input contract for generating a grounded segmentation report."""

    file_name: str | None = Field(default=None, alias="fileName", max_length=180)
    image_type: str | None = Field(default=None, alias="imageType", max_length=80)
    image_size_bytes: int | None = Field(default=None, alias="imageSizeBytes", ge=0)
    metrics: CaseMetrics | None = None


class PromptTrace(ApiModel):
    """Audit metadata showing how the report was produced."""

    mode: Literal["llm", "deterministic-fallback"]
    model: str
    provider: Literal["azure-openai", "openai", "local"]
    prompt_version: str = Field(default=PROMPT_VERSION, alias="promptVersion")
    latency_ms: int = Field(alias="latencyMs")
    retrieved_context: list[str] = Field(alias="retrievedContext")
    fallback_reason: str | None = Field(default=None, alias="fallbackReason")


class CaseReport(ApiModel):
    """API response shown in the case-report panel."""

    summary: str = Field(min_length=1, max_length=600)
    observations: list[ReportItem] = Field(min_length=1, max_length=6)
    quality_checks: list[ReportItem] = Field(alias="qualityChecks", min_length=1, max_length=6)
    prompt_trace: PromptTrace = Field(alias="promptTrace")


class LlmReportPayload(ApiModel):
    """Strict subset of fields accepted from the LLM response."""

    summary: str = Field(min_length=1, max_length=600)
    observations: list[ReportItem] = Field(default_factory=list, max_length=6)
    quality_checks: list[ReportItem] = Field(default_factory=list, alias="qualityChecks", max_length=6)


@dataclass(frozen=True)
class ProviderConfig:
    """Normalized chat-completion settings for Azure OpenAI or OpenAI."""

    provider: Literal["azure-openai", "openai"]
    url: str
    model: str
    headers: dict[str, str]
    body_fields: dict[str, Any]


@dataclass(frozen=True)
class GenerationSettings:
    """Runtime knobs for latency, retry, and output-size control."""

    timeout_seconds: float
    max_retries: int
    max_output_tokens: int


@dataclass(frozen=True)
class GenerationResult:
    """LLM generation outcome plus the reason fallback may be needed."""

    report: CaseReport | None
    fallback_reason: str | None = None


def generation_settings() -> GenerationSettings:
    """Read bounded generation settings from environment variables."""

    return GenerationSettings(
        timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        max_retries=_env_int("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        max_output_tokens=_env_int("LLM_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
    )


def provider_config() -> ProviderConfig | None:
    """Resolve the configured LLM provider, preferring Azure OpenAI.

    Azure is checked first because it is common in enterprise healthcare
    deployments; the plain OpenAI API remains available for local demos and
    simpler portfolio deployments.
    """

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    openai_key = os.getenv("OPENAI_API_KEY")

    azure_values = [azure_endpoint, azure_key, azure_deployment]
    if any(azure_values) and not all(azure_values):
        logger.warning(
            "Azure OpenAI is partially configured; set endpoint, deployment, and API key to enable it."
        )

    if azure_endpoint and azure_key and azure_deployment:
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_API_VERSION)
        return ProviderConfig(
            provider="azure-openai",
            url=(
                f"{azure_endpoint.rstrip('/')}/openai/deployments/"
                f"{azure_deployment}/chat/completions?api-version={api_version}"
            ),
            model=azure_deployment,
            headers={"api-key": azure_key},
            body_fields={},
        )

    if openai_key:
        model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        return ProviderConfig(
            provider="openai",
            url="https://api.openai.com/v1/chat/completions",
            model=model,
            headers={"Authorization": f"Bearer {openai_key}"},
            body_fields={"model": model},
        )

    return None


def build_fallback_report(
    request: CaseReportRequest,
    *,
    latency_ms: int = 0,
    reason: str = "llm-not-configured",
) -> CaseReport:
    """Create a deterministic report when the LLM is unavailable or invalid.

    The fallback preserves the API shape and prompt trace so the UI can explain
    degraded operation instead of failing the workflow.
    """

    metrics = request.metrics
    area = f"{metrics.pred_area_pct:.1f}%" if metrics else "not available"
    has_ground_truth = bool(metrics and metrics.dice is not None and metrics.iou is not None)
    dice = f"{metrics.dice * 100:.1f}%" if metrics and metrics.dice is not None else "not supplied"
    iou = f"{metrics.iou * 100:.1f}%" if metrics and metrics.iou is not None else "not supplied"

    quality_checks = quality_checks_for(metrics, has_ground_truth=has_ground_truth)

    return CaseReport(
        summary=(
            f"Segmentation completed for {request.file_name or 'the uploaded dermoscopy image'}. "
            f"The predicted lesion mask covers {area} of the image. "
            "This report explains model output quality, not diagnosis."
        ),
        observations=[
            f"Predicted lesion area: {area}.",
            f"Ground-truth comparison is available: Dice {dice}, IoU {iou}."
            if has_ground_truth
            else "No ground-truth mask was supplied, so agreement metrics are unavailable.",
            "The segmentation mask can support measurement, review, and annotation workflows, but it should not be used alone for clinical decisions.",
        ],
        qualityChecks=quality_checks,
        promptTrace=PromptTrace(
            mode="deterministic-fallback",
            model="local-template",
            provider="local",
            latencyMs=latency_ms,
            retrievedContext=CLINICAL_CONTEXT,
            fallbackReason=reason,
        ),
    )


def quality_checks_for(metrics: CaseMetrics | None, *, has_ground_truth: bool) -> list[str]:
    """Derive deterministic engineering checks from segmentation metrics."""

    if metrics is None:
        return [
            "Segmentation metrics were not supplied with this report request.",
            "Review the generated mask overlay before using the result downstream.",
            "Add a ground-truth mask to enable Dice, IoU, sensitivity, and specificity tracking.",
        ]

    checks = [
        "Predicted lesion area is present and measurable.",
        "No extreme full-image mask detected.",
        "Add a ground-truth mask to enable Dice, IoU, sensitivity, and specificity tracking.",
    ]

    if metrics.pred_area_pct < 1:
        checks[0] = "Very small predicted area; verify that the lesion is visible and centered."
    if metrics.pred_area_pct > 70:
        checks[1] = "Large predicted area; inspect for failed foreground/background separation."
    if has_ground_truth:
        checks[2] = "Ground-truth overlap metrics can be tracked in model evaluation dashboards."

    return checks


def build_report_prompt(request: CaseReportRequest) -> str:
    """Build the compact JSON prompt sent as the user message.

    The prompt carries an explicit output contract and safety requirements so the
    model has less room to drift into diagnosis or unsupported clinical claims.
    """

    return json.dumps(
        {
            "task": "Create a concise structured engineering report for a dermoscopy segmentation result.",
            "outputContract": REPORT_JSON_SCHEMA,
            "requirements": REPORT_REQUIREMENTS,
            "promptVersion": PROMPT_VERSION,
            "retrievedContext": CLINICAL_CONTEXT,
            "image": {
                "fileName": request.file_name,
                "imageType": request.image_type,
                "imageSizeBytes": request.image_size_bytes,
            },
            "metrics": request.metrics.model_dump(by_alias=True, exclude_none=True) if request.metrics else None,
        },
        separators=(",", ":"),
    )


def chat_completion_body(request: CaseReportRequest, settings: GenerationSettings, provider: ProviderConfig) -> dict[str, Any]:
    """Assemble the provider-compatible chat-completion request body."""

    return {
        **provider.body_fields,
        "temperature": 0.2,
        "max_tokens": settings.max_output_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_report_prompt(request)},
        ],
    }


def parse_chat_completion_content(response_json: dict[str, Any]) -> str | None:
    """Extract message content from a chat-completion response defensively."""

    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None

    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None

    content = message.get("content")
    return content if isinstance(content, str) and content.strip() else None


def normalise_json_content(content: str) -> str:
    """Strip optional markdown fences before JSON validation."""

    stripped = content.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return fence_match.group(1).strip() if fence_match else stripped


def payload_to_report(
    payload: LlmReportPayload,
    *,
    provider: ProviderConfig,
    latency_ms: int,
) -> CaseReport:
    """Convert validated LLM JSON into the public report response."""

    observations = payload.observations or ["The model returned a summary without detailed observations."]
    quality_checks = payload.quality_checks or ["Review the segmentation overlay before using this result downstream."]

    return CaseReport(
        summary=payload.summary,
        observations=observations,
        qualityChecks=quality_checks,
        promptTrace=PromptTrace(
            mode="llm",
            model=provider.model,
            provider=provider.provider,
            latencyMs=latency_ms,
            retrievedContext=CLINICAL_CONTEXT,
        ),
    )


def should_retry(status_code: int) -> bool:
    """Retry only transient LLM API failures."""

    return status_code == 429 or 500 <= status_code <= 599


async def call_llm_report(request: CaseReportRequest) -> GenerationResult:
    """Call the configured LLM and validate its structured report.

    Failures are captured as fallback reasons rather than raised to the API
    layer, keeping report generation resilient for demos and production use.
    """

    provider = provider_config()
    if provider is None:
        return GenerationResult(report=None, fallback_reason="llm-not-configured")

    settings = generation_settings()
    started = time.perf_counter()
    body = chat_completion_body(request, settings, provider)
    timeout = httpx.Timeout(settings.timeout_seconds, connect=min(5.0, settings.timeout_seconds))
    last_failure = "llm-request-failed"

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(settings.max_retries + 1):
            try:
                response = await client.post(
                    provider.url,
                    headers={"Content-Type": "application/json", **provider.headers},
                    json=body,
                )
            except httpx.TimeoutException:
                last_failure = "llm-timeout"
                logger.warning("LLM report request timed out provider=%s attempt=%s", provider.provider, attempt + 1)
            except httpx.HTTPError as exc:
                last_failure = "llm-network-error"
                logger.warning("LLM report request failed provider=%s attempt=%s error=%s", provider.provider, attempt + 1, exc)
            else:
                if response.status_code < 400:
                    try:
                        content = parse_chat_completion_content(response.json())
                        if content is None:
                            return GenerationResult(report=None, fallback_reason="llm-empty-response")
                        payload = LlmReportPayload.model_validate_json(normalise_json_content(content))
                    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                        logger.warning("LLM report payload validation failed provider=%s error=%s", provider.provider, exc)
                        return GenerationResult(report=None, fallback_reason="llm-invalid-json")

                    return GenerationResult(
                        report=payload_to_report(
                            payload,
                            provider=provider,
                            latency_ms=round((time.perf_counter() - started) * 1000),
                        )
                    )

                last_failure = f"llm-http-{response.status_code}"
                if not should_retry(response.status_code):
                    logger.warning("LLM report request rejected provider=%s status=%s", provider.provider, response.status_code)
                    return GenerationResult(report=None, fallback_reason=last_failure)

                logger.warning("LLM report request retryable failure provider=%s status=%s attempt=%s", provider.provider, response.status_code, attempt + 1)

            if attempt < settings.max_retries:
                await asyncio.sleep(min(0.25 * (2 ** attempt), 2.0))

    return GenerationResult(report=None, fallback_reason=last_failure)


async def generate_case_report(request: CaseReportRequest) -> CaseReport:
    """Generate a case report, using deterministic fallback when needed."""

    started = time.perf_counter()
    result = await call_llm_report(request)
    if result.report:
        return result.report

    return build_fallback_report(
        request,
        latency_ms=round((time.perf_counter() - started) * 1000),
        reason=result.fallback_reason or "llm-unavailable",
    )
