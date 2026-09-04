"""LLM HTTP client: request execution, retry policy, and response parsing.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import AsyncIterator

import httpx

from .models import CaseReport, CaseReportRequest
from .prompt import ReportPromptBuilder
from .provider import ProviderConfig, auth_headers
from .response_parser import LlmReportSchema, LlmResponseError, LlmResponseParser, make_report_from_llm_response
from .util import collapse_for_log, response_body_text

logger = logging.getLogger(__name__)


DEFAULT_MAX_OUTPUT_TOKENS = 1024
"""int: Maximum tokens requested in the LLM completion response.
"""

DEFAULT_TOTAL_BUDGET_SECONDS = 40.0
"""float: Overall wall-clock ceiling across all HTTP attempts (initial plus
retries) for one report generation call.
Configured to remain below the upstream Express service's timeout.
"""

DEFAULT_ATTEMPT_TIMEOUT_SECONDS = 25.0
"""float: Wall-clock ceiling on one HTTP attempt, enforced by ``asyncio.wait_for``.
"""

DEFAULT_SILENCE_TIMEOUT_SECONDS = 15.0
"""float: Longest gap httpx will tolerate between I/O events on one attempt
(connect, write, read, and waiting for a pooled connection all share this
value).
"""

DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
"""float: Maximum time to establish a TCP connection to the provider.
"""

DEFAULT_MAX_RETRIES = 2
"""int: Number of retry attempts allowed after the first attempt fails.
"""

MIN_ATTEMPT_SECONDS = 2.0
"""float: Minimum remaining budget required to start a new attempt.

The value is checked twice against ``remaining()`` (total budget minus elapsed time):
before each attempt begins, and before sleeping for backoff between
retries (against budget as it would be *after* that sleep).
"""

BASE_BACKOFF_SECONDS = 0.25
"""float: First retry wait, doubled on each subsequent attempt.
"""

MAX_BACKOFF_SECONDS = 2.0
"""float: Ceiling on our own exponential backoff, so raising
``max_retries`` cannot grow the wait without bound.
"""

RETRYABLE_RESPONSE_REASONS = frozenset({"llm-invalid-json"})
"""frozenset[str]: Failure reasons on an HTTP 200 response that are retryable.
"""


@dataclass(frozen=True)
class GenerationSettings:
    """Runtime configuration for LLM report generation that controls
    per-attempt latency, retry count, output size, and the overall
    wall-clock budget across all attempts.

    Args:
        attempt_timeout_seconds: Wall-clock ceiling on a single HTTP attempt,
            i.e., one call to ``client.post()``. This includes I/O events
            (connect, write, read, and pool-checkout wait
            (``silence_timeout_seconds``)) plus all the gaps between those
            I/O events within the call, wrapped by a single
            ``asyncio.wait_for``.

            It starts when that attempt begins and ends when that attempt's
            ``wait_for`` resolves (success or timeout). Anything the retry
            loop does *between attempts* (backoff sleeps) falls outside this
            interval entirely.
        max_retries: Number of retries permitted after the first attempt.
        max_output_tokens: Upper bound on tokens generated per response.
        silence_timeout_seconds: Longest gap httpx will tolerate between I/O
            events within one attempt — passed as the single-argument form
            of ``httpx.Timeout``, so it covers connect, write, read, and
            pool-checkout wait alike.
        connect_timeout_seconds: Maximum time to establish the TCP
            connection.
        total_budget_seconds: Hard wall-clock ceiling across every attempt
            and backoff sleep combined. Deliberately lower than the
            uncapped duration, which is ``attempt_timeout_seconds *
            (max_retries + 1)`` plus the sleeps between attempts: at the
            defaults, ``25 * 3`` seconds for 2 retries (3 attempts) plus
            ``0.25 + 0.5`` of backoff, i.e., approximately 76 seconds
            against a 40-second budget.

            This service is invoked from an Express route that enforces its
            own timeout. ``total_budget_seconds`` must therefore be set
            strictly less than that timeout, with sufficient margin, so that
            this layer always times out first and returns a deterministic
            fallback report rather than the caller receiving a bare 504 from
            the upstream Express route.
    """
    attempt_timeout_seconds: float = DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    total_budget_seconds: float = DEFAULT_TOTAL_BUDGET_SECONDS
    silence_timeout_seconds: float = DEFAULT_SILENCE_TIMEOUT_SECONDS
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class GenerationResult:
    """Outcome of one LLM report-generation attempt.

    Carries either a completed report or the reason a fallback is needed,
    along with enough context for the caller to decide whether to retry.

    Args:
        report: The generated report, or ``None`` if generation failed.
        fallback_reason: Stable reason explaining why ``report`` is
            ``None``. Unused when ``report`` is set.
        elapsed_ms: Wall-clock time spent on the LLM path, including failed
            attempts. Populated even when ``report`` is ``None`` so a
            deterministic fallback can report it.
        retryable: Whether another attempt could plausibly succeed. Decided
            here rather than by the caller, since only this layer observes
            both the HTTP status and the response-level failure reason: an
            HTTP 200 response that fails validation is retryable
            even though its status code reports success.
        retry_after_seconds (float, optional): Delay, in seconds, requested
            by the provider via the ``Retry-After`` header of the response
            that produced this result. ``None`` if the response carried no
            such header. When present, this value takes precedence over the
            caller's own exponential backoff schedule.
    """
    report: CaseReport | None
    fallback_reason: str | None = None
    elapsed_ms: int = 0
    retryable: bool = False
    retry_after_seconds: float | None = None


class LlmReportClient:
    """Calls the configured LLM provider and returns validated reports."""

    def __init__(
        self,
        *,
        provider: ProviderConfig,
        settings: GenerationSettings,
        prompt_builder: ReportPromptBuilder | None = None,
        parser: LlmResponseParser | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Construct a client for one provider.

        Args:
            provider: Resolved provider configuration to call.
            settings: Settings for per-attempt latency, retry count,
                output size, and the overall wall-clock budget
            prompt_builder: Builds the chat request body. Defaults to a new
                :class:`ReportPromptBuilder`.
            parser: Extracts and validates the report content from each
                response. Defaults to a new :class:`LlmResponseParser`.
            http_client: An existing HTTP client to send requests through.
                One shared client is created when the app
                starts and passed in here for every request (see
                ``lifespan`` in ``main.py``).
        """
        self.provider = provider
        self.settings = settings
        self.prompt_builder = prompt_builder or ReportPromptBuilder()
        self.parser = parser or LlmResponseParser()
        self.http_client = http_client

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        """Provide a client for ``generate`` to use. Two options:

        - An *injected* client (``self.http_client``) was opened elsewhere
          (in production, once for the whole app's lifetime — see
          ``lifespan`` in ``main.py``) and is still needed by other
          requests after this one finishes.
        - A client created *by this method* belongs to this one call only.
          It is opened in its own ``async with`` block, so it closes
          automatically once this call is done using it, for example, in tests.

        Mechanics: ``@asynccontextmanager`` turns this async generator into
        an async context manager — code before ``yield`` runs on
        ``__aenter__``, the yielded value becomes the ``as`` target, and
        code after ``yield`` runs on ``__aexit__``. The ``AsyncIterator``
        return type is what the decorator requires on the undecorated
        function signature.

        In this codebase, the *injected* branch is the one production
        traffic takes: ``main.py``'s ``POST /case-report`` handler passes
        ``http_request.app.state.llm_http_client`` (the client ``lifespan``
        opened once at startup) all the way through
        ``generate_case_report`` -> ``CaseReportGenerator`` ->
        ``LlmReportClient``. That client's own closing is governed by a
        *different* ``__aexit__`` entirely: ``lifespan`` is itself an
        ``@asynccontextmanager``, and the code after its ``yield`` (which
        exits its ``async with httpx.AsyncClient(...)`` and closes the
        client) only runs when Starlette calls ``lifespan``'s ``__aexit__``
        at app shutdown — a trigger this method never sees, which is why
        this branch must not close the client itself.
        """

        if self.http_client is not None:
            yield self.http_client
            return

        # silence_timeout_seconds is reused here since httpx uses it everywhere else in this class
        async with httpx.AsyncClient(timeout=self.settings.silence_timeout_seconds) as client:
            # Caller's `async with self._client()` exiting resumes this generator
            # past `yield`, which exits this `async with` and closes `client`.
            yield client

    async def generate(self, request: CaseReportRequest) -> GenerationResult:
        """Request a report from the LLM.

        Builds the chat request once, then attempts it up to
        ``settings.max_retries + 1`` times, stopping early on a successful
        or non-retryable result. Each attempt is bounded by
        ``attempt_timeout_seconds`` and the loop as a whole by
        ``total_budget_seconds``; retries back off per :func:`backoff_seconds`,
        honoring the provider's ``Retry-After`` when present.

        Args:
            request: The case data to build the prompt from.

        Returns:
            A :class:`GenerationResult` with the parsed report on success,
            or ``fallback_reason`` set when every attempt failed or the
            budget ran out first.
        """
        started = time.perf_counter()
        body = self.prompt_builder.build_chat_body(request, settings=self.settings, provider=self.provider)
        last_failure = "llm-request-failed"

        def remaining() -> float:
            """Seconds left in the total budget; negative once it is spent."""
            return self.settings.total_budget_seconds - (time.perf_counter() - started)

        # By this point the budget clock has started, the request body is
        # built, and the default failure reason is set in case every attempt
        # below fails before producing a more specific one. Now acquire the
        # HTTP client to run the attempt/retry loop against.
        async with self._client() as client:
            for attempt in range(self.settings.max_retries + 1):
                # requested_wait must be reset on each new attempt
                requested_wait: float | None = None
                left = remaining()
                if left < MIN_ATTEMPT_SECONDS:
                    logger.warning(
                        "LLM report budget exhausted provider=%s attempt=%s elapsed_ms=%s reason=%s",
                        self.provider.provider,
                        attempt + 1,
                        self._elapsed_ms(started),
                        last_failure,
                    )
                    break

                try:
                    # httpx's timeout bounds the gap between I/O events
                    http_timeout = httpx.Timeout(
                        min(self.settings.silence_timeout_seconds, left),
                        connect=min(
                            self.settings.connect_timeout_seconds,
                            self.settings.silence_timeout_seconds,
                            left,
                        ),
                    )
                    # attempt_timeout_seconds wrapped in asyncio.wait_for is the wall-clock ceiling on a single
                    # HTTP attempt, incl. I/O events and all the gaps in-between
                    response = await asyncio.wait_for(
                        client.post(
                            self.provider.url,
                            headers={"Content-Type": "application/json", **auth_headers(self.provider)},
                            json=body,
                            timeout=http_timeout,
                        ),
                        timeout=min(self.settings.attempt_timeout_seconds, left),
                    )
                # - httpx.TimeoutException is a base class covering httpx.ConnectTimeout,
                # httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout (unreachable host)
                # - httpx.TimeoutException is a subclass of httpx.HTTPError,
                # so the timeout clause comes first to be reached
                # - asyncio.TimeoutError is raised by the outer asyncio.wait_for(...,) (slow generation)
                except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                    last_failure = "llm-timeout"
                    logger.warning(
                        "LLM report request timed out provider=%s attempt=%s elapsed_ms=%s error=%s",
                        self.provider.provider,
                        attempt + 1,
                        self._elapsed_ms(started),
                        type(exc).__name__,
                    )
                # httpx.HTTPError catches non-timeout failures (DNS failure, connection refused, TLS errors, etc.)
                except httpx.HTTPError as exc:
                    last_failure = "llm-network-error"
                    logger.warning(
                        "LLM report request failed provider=%s attempt=%s elapsed_ms=%s error=%s",
                        self.provider.provider,
                        attempt + 1,
                        self._elapsed_ms(started),
                        exc,
                    )
                #
                # ##### success case - the actual report object is returned by _handle_response #####
                else:
                    result = self._handle_response(response, started_at=started)
                    if result.report or not result.retryable:
                        return result

                    last_failure = result.fallback_reason or last_failure
                    requested_wait = result.retry_after_seconds
                    logger.warning(
                        "LLM report request retryable failure provider=%s status=%s attempt=%s elapsed_ms=%s",
                        self.provider.provider,
                        response.status_code,
                        attempt + 1,
                        self._elapsed_ms(started),
                    )

                # after a failed attempt, compute the retry delay
                # and await before looping around for another attempt
                if attempt < self.settings.max_retries:
                    backoff = backoff_seconds(attempt, requested_wait)
                    left_now = remaining()
                    if left_now - backoff < MIN_ATTEMPT_SECONDS:
                        if requested_wait:
                            logger.warning(
                                "LLM report giving up early provider=%s retry_after=%ss exceeds remaining budget=%.1fs",
                                self.provider.provider,
                                requested_wait,
                                left_now,
                            )
                        break
                    await asyncio.sleep(backoff)

        return GenerationResult(
            report=None,
            fallback_reason=last_failure,
            elapsed_ms=self._elapsed_ms(started),
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return round((time.perf_counter() - started_at) * 1000)

    def _handle_response(self, response: httpx.Response, *, started_at: float) -> GenerationResult:
        """Turn one completed HTTP response into a ``GenerationResult``.

        This method is called only when ``client.post()`` actually returned a response
        (no timeout or network error). It never raises itself, so the retry
        loop in ``generate`` can always inspect ``result.report`` /
        ``result.retryable`` without a try/except of its own. Three
        outcomes are distinguished, each carrying its own ``fallback_reason``
        and ``retryable`` verdict:

        1. HTTP status >= 400: the provider rejected the request outright.
           ``retryable`` is decided by :func:`should_retry` (429/5xx only),
           and any ``Retry-After`` header is captured for the backoff step.
        2. HTTP 200 but the body fails to parse/validate (not JSON, or JSON
           that does not satisfy :class:`LlmResponseParser`): a model-level
           failure (refusal, truncation, empty choices) or an intermediary
           (proxy/gateway) answering with a non-JSON body instead of the
           model ever being reached — see the inline comments below for how
           these are told apart and why only some are retryable.
        3. HTTP 200 with a valid response: converted into a real report via
           ``make_report_from_llm_response``.

        Args:
            response: The completed HTTP response to interpret.
            started_at: ``time.perf_counter()`` value from when generation
                began, used to compute ``elapsed_ms`` on the result.

        Returns:
            A ``GenerationResult`` carrying either the parsed report, or a
            ``fallback_reason``/``retryable`` pair describing why it failed.
        """
        if response.status_code >= 400:
            retry_after = retry_after_seconds(response)
            # The status code alone can't tell a per-minute rate limit from an
            # exhausted daily quota, an unaffordable request, or a dead model —
            # all of which arrive as 429 or 402 with the explanation in the body.
            logger.warning(
                "LLM report request rejected provider=%s model=%s status=%s retry_after=%s body=%s",
                self.provider.provider,
                self.provider.model,
                response.status_code,
                retry_after,
                collapse_for_log(response_body_text(response)),
            )
            return GenerationResult(
                report=None,
                fallback_reason=f"llm-http-{response.status_code}",
                elapsed_ms=self._elapsed_ms(started_at),
                retryable=should_retry(response.status_code),
                retry_after_seconds=retry_after,
            )
        #
        # status_code < 400 here (the branch above returns on transport/protocol
        # rejection), so status_code has nothing more to say — a 200 can still
        # wrap a body that isn't a usable completion (non-JSON error page,
        # refusal, truncation, empty choices). The only way to find that out
        # is to actually parse it, and the parser signals failure by raising
        # rather than returning something branchable, hence try/except here
        # instead of another status_code check.
        try:
            llm_report_schema: LlmReportSchema = self.parser.parse_llm_response(response.json())
        except LlmResponseError as exc:
            # This one warning covers every reason LlmResponseError can carry
            # (invalid JSON, a refusal, a truncation, an empty choices list, etc.)
            logger.warning(
                "LLM report response unusable provider=%s model=%s reason=%s detail=%s",
                self.provider.provider,
                self.provider.model,
                exc.fallback_reason,
                exc.detail,
            )
            return GenerationResult(
                report=None,
                fallback_reason=exc.fallback_reason,
                elapsed_ms=self._elapsed_ms(started_at),
                retryable=exc.fallback_reason in RETRYABLE_RESPONSE_REASONS,
            )
        except ValueError as exc:
            # response.json() itself failed as the raw HTTP body isn't JSON at all
            logger.warning(
                "LLM report response was not JSON provider=%s model=%s error=%s body=%s",
                self.provider.provider,
                self.provider.model,
                exc,
                collapse_for_log(response_body_text(response)),
            )
            return GenerationResult(
                report=None,
                fallback_reason="llm-invalid-response",
                elapsed_ms=self._elapsed_ms(started_at),
                retryable=True,
            )
        #
        # ##### success case - the actual report object #####
        return GenerationResult(
            report=make_report_from_llm_response(
                llm_report_schema,
                provider=self.provider,
                latency_ms=self._elapsed_ms(started_at),
            )
        )


def retry_after_seconds(response: httpx.Response) -> float | None:
    r"""Parse the ``Retry-After`` header of an HTTP response into a delay.

    Supports both forms permitted by `RFC 7231, Section 7.1.3
    <https://www.rfc-editor.org/rfc/rfc7231#section-7.1.3>`_: a delay
    expressed as an integer number of seconds, or an absolute HTTP-date.

    Args:
        response (httpx.Response): The HTTP response whose headers are
            searched for ``Retry-After``.

    Returns:
        float, optional: The delay in seconds the provider asked the caller
        to wait, or ``None`` if the header is absent from ``response`` or
        cannot be parsed as either permitted form — in which case the
        caller falls back to its own exponential backoff schedule.

        .. note::
            An HTTP-date already in the past is clamped to ``0.0``
            ("retry immediately") rather than returned as a negative
            duration.
    """

    raw = response.headers.get("Retry-After")
    if not raw:
        return None

    raw = raw.strip()
    try:
        return max(float(raw), 0.0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("Ignoring unparseable Retry-After=%r: %s", raw, exc)
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)


def should_retry(status_code: int) -> bool:
    """Retry only transient LLM API failures.

    429 (rate limited) and 5xx (provider-side error) are treated as
    transient — the same request has a reasonable chance of succeeding
    on a later attempt. Every other 4xx (400 bad request, 401/403 auth,
    402 quota/billing, 404 wrong model/URL, etc.) is deterministic given
    the same request, so retrying would just burn the attempt budget for
    no chance of a different outcome.
    """

    return status_code == 429 or 500 <= status_code <= 599


def backoff_seconds(attempt: int, requested_wait: float | None) -> float:
    """How long to wait before retrying ``attempt``.

    Args:
        attempt: Zero-based index of the attempt that just failed.
        requested_wait: The provider's ``Retry-After``, or ``None``.

    Returns:
        The longer of the exponential backoff and ``requested_wait``. The
        backoff curve is a heuristic estimate; ``Retry-After`` is the
        provider stating the answer, so it can only ever lengthen the wait.
        Retrying before a rate limit resets cannot succeed and still spends
        quota.
    """

    ours = min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
    return max(ours, requested_wait or 0.0)
