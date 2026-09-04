"""Grounded LLM reporting for SkiNet segmentation results.

This package keeps the public FastAPI contract small while separating the
reporting workflow into explicit layers, one module per layer:

- models: API request/response shape (Pydantic models + shared constants).
- provider: turns environment variables into a normalized client configuration
  (Mistral by default, OpenRouter as fallback).
- prompt: owns model instructions, prompt construction, and output contracts.
- client: owns HTTP, retry, timeout, and response parsing against the LLM,
  scoped to a single report request under a latency budget.
- status: checks whether the configured provider is reachable and serving the
  configured model, for the on-demand health probe rather than the report path.
- fallback: builds a deterministic report when live generation is unavailable.
- generator: orchestrates LLM-first generation with deterministic fallback.
- util: safe response-body logging, shared by client and status.

The generated content is for engineering review of segmentation output only;
it must not make clinical claims.
"""

from .client import (
    GenerationResult,
    GenerationSettings,
    LlmReportClient,
    backoff_seconds,
    should_retry,
)
from .fallback import DeterministicReportBuilder, build_fallback_report, quality_checks_for
from .generator import CaseReportGenerator, generate_case_report
from .models import CaseMetrics, CaseReport, CaseReportRequest, LlmReportSchema, ProviderStatus, ReportMetadata
from .prompt import ReportPromptBuilder, build_chat_completion_body, build_report_prompt
from .provider import (
    EnvironmentProviderResolver,
    FirstConfiguredResolver,
    ProviderConfig,
    ProviderResolver,
    create_default_resolver,
    create_mistral_resolver,
    create_openrouter_resolver,
)
from .response_parser import (
    LlmResponseError,
    LlmResponseParser,
    normalise_json_content,
    make_report_from_llm_response,
)
from .status import check_provider_status

__all__ = [
    "CaseMetrics",
    "CaseReport",
    "CaseReportGenerator",
    "CaseReportRequest",
    "DeterministicReportBuilder",
    "EnvironmentProviderResolver",
    "FirstConfiguredResolver",
    "GenerationResult",
    "GenerationSettings",
    "LlmReportClient",
    "LlmReportSchema",
    "LlmResponseError",
    "LlmResponseParser",
    "ProviderStatus",
    "ReportMetadata",
    "ProviderConfig",
    "ProviderResolver",
    "ReportPromptBuilder",
    "backoff_seconds",
    "build_chat_completion_body",
    "build_fallback_report",
    "build_report_prompt",
    "check_provider_status",
    "create_default_resolver",
    "create_mistral_resolver",
    "create_openrouter_resolver",
    "generate_case_report",
    "normalise_json_content",
    "make_report_from_llm_response",
    "quality_checks_for",
    "should_retry",
]
