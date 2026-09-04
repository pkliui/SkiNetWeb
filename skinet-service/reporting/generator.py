"""Orchestrates LLM-first report generation with deterministic fallback."""

import logging

import httpx

from .client import GenerationResult, GenerationSettings, LlmReportClient
from .fallback import DeterministicReportBuilder
from .models import CaseReport, CaseReportRequest
from .provider import ProviderResolver, create_default_resolver

logger = logging.getLogger(__name__)


class CaseReportGenerator:
    """LLM report generation with a deterministic fallback if it fails."""

    def __init__(
        self,
        *,
        provider_resolver: ProviderResolver | None = None,
        settings: GenerationSettings | None = None,
        fallback_builder: DeterministicReportBuilder | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Construct a generator.

        Each argument below defaults to a real, working implementation, so
        calling ``CaseReportGenerator()`` with no arguments is enough for
        normal (non-test) use. Tests pass in fakes/mocks instead.

        Args:
            provider_resolver: Resolves which LLM provider to call. Defaults
                to :func:`create_default_resolver`; override in tests.
            settings: Generation runtime settings. Defaults to a new
                :class:`GenerationSettings`; override in tests.
            fallback_builder: Builds the deterministic fallback report.
                Defaults to a new :class:`DeterministicReportBuilder`;
                override in tests.
            http_client: Shared HTTP client passed through to
                :class:`LlmReportClient` so reports reuse
                connections instead of re-handshaking per request. Passed
                straight through: this class does not own or close it.
        """
        self.provider_resolver = provider_resolver or create_default_resolver()
        self.settings = settings or GenerationSettings()
        self.fallback_builder = fallback_builder or DeterministicReportBuilder()
        self.http_client = http_client

    async def generate(self, request: CaseReportRequest) -> CaseReport:
        """Generate a case report, preferring the LLM path with a fallback.

        Args:
            request: The validated case report request.

        Returns:
            The LLM-generated report if the LLM path succeeded, otherwise a
            deterministic report tagged with the reason the LLM path failed
            and the latency actually spent attempting it.
        """
        result = await self._call_llm(request)
        if result.report:
            return result.report

        return self.fallback_builder.build(
            request,
            reason=result.fallback_reason or "llm-unavailable",
            latency_ms=result.elapsed_ms,
        )

    async def _call_llm(self, request: CaseReportRequest) -> GenerationResult:
        """Attempt the LLM path.

        Args:
            request: The validated case report request.

        Returns:
            A :class:`GenerationResult` with ``fallback_reason`` set to
            ``"llm-not-configured"`` and no further attempt made if no
            provider is configured, otherwise the result of calling
            :class:`LlmReportClient`.
        """
        provider = self.provider_resolver.resolve()
        if provider is None:
            logger.warning(
                "No LLM provider configured; falling back to deterministic report generation"
            )
            return GenerationResult(report=None, fallback_reason="llm-not-configured")

        return await LlmReportClient(
            provider=provider, settings=self.settings, http_client=self.http_client
        ).generate(request)


async def generate_case_report(
    request: CaseReportRequest, *, http_client: httpx.AsyncClient | None = None
) -> CaseReport:
    """Generate a case report, using deterministic fallback when needed.

    Module-level convenience wrapper around a fresh ``CaseReportGenerator``.
    Called from ``main.py``'s ``POST /case-report`` handler with the request
    body FastAPI has already parsed and validated.

    Args:
        request: The validated case report request.
        http_client: Shared HTTP client to issue provider requests through.
            ``main.py`` passes the app-lifetime client so connections are
            reused across reports; ``None`` falls back to a per-call client.

    Returns:
        The generated :class:`CaseReport`.
    """
    return await CaseReportGenerator(http_client=http_client).generate(request)
