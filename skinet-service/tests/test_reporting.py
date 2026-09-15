import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from pydantic import SecretStr, ValidationError

import reporting
from reporting import (
    CaseReportGenerator,
    CaseReportRequest,
    LlmReportSchema,
    ProviderConfig,
    build_fallback_report,
    generate_case_report,
    build_report_prompt,
    check_provider_status,
    create_default_resolver,
    create_mistral_resolver,
    create_openrouter_resolver,
    normalise_json_content,
    backoff_seconds,
    make_report_from_llm_response,
    should_retry,
    LlmResponseError,
    LlmResponseParser,
)
from reporting.client import MAX_BACKOFF_SECONDS
from reporting.models import REPORT_SCHEMA_NAME, STRICT_JSON_SCHEMA_RESPONSE_FORMAT
from reporting.prompt import REPORT_JSON_SCHEMA
from reporting.provider import _resolve_response_format, auth_headers


def test_case_report_request_accepts_camel_case_metrics() -> None:
    request = CaseReportRequest.model_validate(
        {
            "fileName": "case.png",
            "metrics": {"predAreaPct": 12.5, "dice": 0.8, "iou": 0.67},
        }
    )

    assert request.file_name == "case.png"
    assert request.metrics is not None
    assert request.metrics.pred_area_pct == 12.5


def test_fallback_report_uses_aliases_in_api_shape() -> None:
    request = CaseReportRequest.model_validate({"metrics": {"predAreaPct": 0.5}})
    report = build_fallback_report(request, latency_ms=7, reason="unit-test")
    payload = report.model_dump(by_alias=True)

    assert payload["reportMetadata"]["mode"] == "deterministic-fallback"
    assert payload["reportMetadata"]["fallbackReason"] == "unit-test"
    assert payload["reportMetadata"]["latencyMs"] == 7
    assert payload["qualityChecks"][0].startswith("Very small predicted area")


def test_prompt_is_compact_json_and_preserves_metric_alias() -> None:
    request = CaseReportRequest.model_validate({"metrics": {"predAreaPct": 42.0}})
    prompt = json.loads(build_report_prompt(request))

    assert prompt["untrustedInput"]["metrics"]["predAreaPct"] == 42.0
    assert "requirements" in prompt
    assert "diagnosis" in " ".join(prompt["requirements"])
    assert prompt["untrustedInput"]["metrics"] == {"predAreaPct": 42.0}


def test_normalise_json_content_accepts_markdown_fence() -> None:
    content = '```json\n{"summary":"ok"}\n```'

    assert normalise_json_content(content) == '{"summary":"ok"}'


def test_normalise_json_content_passes_through_bare_json() -> None:
    assert normalise_json_content('{"summary":"ok"}') == '{"summary":"ok"}'


def test_normalise_json_content_accepts_fence_without_language_tag() -> None:
    content = '```\n{"summary":"ok"}\n```'

    assert normalise_json_content(content) == '{"summary":"ok"}'


def test_normalise_json_content_accepts_uppercase_json_tag() -> None:
    content = '```JSON\n{"summary":"ok"}\n```'

    assert normalise_json_content(content) == '{"summary":"ok"}'


@pytest.mark.parametrize(
    "content",
    [
        "not valid json at all",
        "{",
        '{"a": }',
        "\x00\x01binary garbage",
        "null",
        "[1,2,3]",
        '"just a string"',
        '{"summary": "ok", }',
    ],
)
def test_syntactically_invalid_content_raises_llm_response_error(content: str) -> None:
    """Content that isn't JSON at all still surfaces as one typed failure.

    Guards the ``except`` clause in ``parse_llm_response``: pydantic v2's
    ``model_validate_json`` raises its own ``ValidationError`` for every
    flavour of broken JSON syntax tried here (not ``json.JSONDecodeError``),
    so this pins down which exception type actually needs to be caught.
    """

    response_json = {"choices": [{"message": {"content": content}}]}

    with pytest.raises(LlmResponseError) as exc_info:
        LlmResponseParser().parse_llm_response(response_json)

    assert exc_info.value.fallback_reason == "llm-invalid-json"
    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert not isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_retry_policy_only_retries_rate_limits_and_server_errors() -> None:
    assert should_retry(429)
    assert should_retry(500)
    assert should_retry(503)
    assert not should_retry(400)
    assert not should_retry(401)


def test_backoff_doubles_each_attempt_then_stops_at_the_ceiling() -> None:
    waits = [backoff_seconds(attempt, None) for attempt in range(6)]

    assert waits[:4] == [0.25, 0.5, 1.0, 2.0]
    # The ceiling matters only if max_retries is raised past its default,
    # which is exactly when an uncapped curve would sleep the budget away.
    assert waits[4:] == [MAX_BACKOFF_SECONDS, MAX_BACKOFF_SECONDS]


def test_backoff_waits_as_long_as_the_provider_asked() -> None:
    # A rate limit that resets in 60s cannot be retried around in 0.25s, so
    # Retry-After overrides our curve however early in the retries it arrives.
    assert backoff_seconds(0, 60.0) == 60.0


def test_backoff_ignores_a_retry_after_shorter_than_our_own_curve() -> None:
    # max(), not "prefer Retry-After": the header may only lengthen the wait.
    assert backoff_seconds(3, 0.5) == MAX_BACKOFF_SECONDS


def test_backoff_treats_a_missing_retry_after_as_no_request() -> None:
    # None reaches here whenever the provider sent no header or an
    # unparseable one; it must not be read as "wait zero seconds".
    assert backoff_seconds(2, None) == 1.0


def test_fallback_report_is_truthful_when_metrics_are_missing() -> None:
    report = build_fallback_report(CaseReportRequest(), reason="unit-test")
    payload = report.model_dump(by_alias=True)

    assert "not available" in payload["summary"]
    assert payload["qualityChecks"][0] == "Segmentation metrics were not supplied with this report request."


def test_llm_payload_rejects_empty_report_items() -> None:
    with pytest.raises(ValidationError):
        LlmReportSchema.model_validate({"summary": "ok", "observations": [""]})


def test_llm_payload_requires_observations_and_quality_checks() -> None:
    with pytest.raises(ValidationError):
        LlmReportSchema.model_validate({"summary": "Mask covers a small lesion region."})


def test_llm_payload_rejects_snake_case_keys() -> None:
    with pytest.raises(ValidationError):
        LlmReportSchema.model_validate(
            {
                "summary": "Mask covers a small lesion region.",
                "observations": ["Predicted lesion area is 12.5%."],
                "quality_checks": ["Inspect the overlay against the source image."],
            }
        )


def test_report_json_schema_keys_match_llm_payload_aliases() -> None:
    expected = {field.alias or name for name, field in LlmReportSchema.model_fields.items()}
    assert set(REPORT_JSON_SCHEMA["properties"]) == expected
    assert set(REPORT_JSON_SCHEMA["required"]) == expected


def test_report_json_schema_advertises_enforced_constraints() -> None:
    """The contract shown to the LLM must state the limits the validator enforces."""

    properties = REPORT_JSON_SCHEMA["properties"]
    assert REPORT_JSON_SCHEMA["additionalProperties"] is False
    assert properties["summary"]["maxLength"] == 600
    for key in ("observations", "qualityChecks"):
        assert properties[key]["minItems"] == 1
        assert properties[key]["maxItems"] == 6
        assert properties[key]["items"]["maxLength"] == 240


def test_report_json_schema_omits_developer_facing_noise() -> None:
    assert "description" not in REPORT_JSON_SCHEMA
    assert all("title" not in prop for prop in REPORT_JSON_SCHEMA["properties"].values())
    assert all(prop["description"] for prop in REPORT_JSON_SCHEMA["properties"].values())


def test_strict_response_format_wraps_the_report_schema() -> None:
    assert STRICT_JSON_SCHEMA_RESPONSE_FORMAT["type"] == "json_schema"
    json_schema = STRICT_JSON_SCHEMA_RESPONSE_FORMAT["json_schema"]
    assert json_schema["strict"] is True
    assert json_schema["name"] == REPORT_SCHEMA_NAME
    assert json_schema["schema"] == REPORT_JSON_SCHEMA


def test_strict_response_format_is_json_serialisable() -> None:
    """The format is serialised into the request body, so no mappingproxy may survive.

    `build_chat_body` shallow-copies with `dict(...)`, so a nested
    MappingProxyType would reach `json.dumps` and raise at request time.
    """

    json.dumps(dict(STRICT_JSON_SCHEMA_RESPONSE_FORMAT))


def test_report_schema_meets_strict_mode_structural_requirements() -> None:
    """Strict mode requires every property to be required and extras forbidden.

    Guards against a future optional field on LlmReportSchema silently making
    the schema invalid for constrained decoding.
    """

    assert REPORT_JSON_SCHEMA["additionalProperties"] is False
    assert set(REPORT_JSON_SCHEMA["required"]) == set(REPORT_JSON_SCHEMA["properties"])


@pytest.mark.parametrize(
    ("structured_outputs", "expected_type"),
    [(False, "json_object"), (True, "json_schema")],
)
def test_resolve_response_format_selects_by_structured_outputs_flag(
    structured_outputs: bool, expected_type: str
) -> None:
    assert _resolve_response_format(structured_outputs)["type"] == expected_type


def test_llm_payload_rejects_unknown_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LlmReportSchema.model_validate(
            {
                "summary": "Mask covers a small lesion region.",
                "observations": ["Predicted lesion area is 12.5%."],
                "qualityChecks": ["Inspect the overlay against the source image."],
                "confidence": 0.92,
            }
        )


def test_make_report_from_llm_response_records_llm_trace() -> None:
    provider = ProviderConfig(
        provider="openrouter",
        url="https://example.test",
        base_url="https://example.test",
        model="gpt-test",
        api_key=SecretStr("test-key"),
        response_format={"type": "json_object"},
    )
    payload = LlmReportSchema.model_validate(
        {
            "summary": "Mask covers a small lesion region.",
            "observations": ["Predicted lesion area is 12.5%."],
            "qualityChecks": ["Inspect the overlay against the source image."],
        }
    )

    report = make_report_from_llm_response(payload, provider=provider, latency_ms=12).model_dump(by_alias=True)

    assert report["reportMetadata"]["mode"] == "llm"
    assert report["reportMetadata"]["model"] == "gpt-test"
    assert report["observations"] == ["Predicted lesion area is 12.5%."]


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        # Matches httpx: header lookup is case-insensitive, and `text` is the
        # raw body the error-path logging reads.
        self.headers = httpx.Headers(headers or {})

    def json(self) -> dict:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload)


class NonJsonResponse(FakeResponse):
    """A 200 whose body is not JSON at all.

    Models an intermediary — proxy, gateway, captive portal — answering in
    place of the provider, which is the only way `response.json()` raises
    before the parser ever runs.
    """

    def __init__(self, body: str) -> None:
        super().__init__(200, {})
        self._body = body

    def json(self) -> dict:
        raise json.JSONDecodeError("Expecting value", self._body, 0)

    @property
    def text(self) -> str:
        return self._body


class FakeAsyncClient:
    posts: list[dict] = []
    responses: list[FakeResponse | Exception] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> None:
        pass

    async def post(self, *args, **kwargs) -> FakeResponse:
        self.posts.append({"args": args, "kwargs": kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeStatusClient:
    """Records status-check GETs and replays a canned response per URL path."""

    gets: list[str] = []
    responses: dict[str, FakeResponse] = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "FakeStatusClient":
        return self

    async def __aexit__(self, *args) -> None:
        pass

    async def get(self, url: str, **kwargs) -> FakeResponse:
        FakeStatusClient.gets.append(url)
        return FakeStatusClient.responses[url]


def test_status_check_skips_the_key_route_for_providers_without_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mistral has no /key route; probing it would 404 and look like an outage."""

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "unit-test-key")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-medium-2604")
    monkeypatch.setattr(reporting.status.httpx, "AsyncClient", FakeStatusClient)
    FakeStatusClient.gets = []
    FakeStatusClient.responses = {
        "https://api.mistral.ai/v1/models": FakeResponse(200, {"data": [{"id": "mistral-medium-2604"}]}),
    }

    status = asyncio.run(check_provider_status(create_mistral_resolver().resolve()))

    assert status.reachable is True and status.reason is None
    assert FakeStatusClient.gets == ["https://api.mistral.ai/v1/models"]


def test_status_check_reports_a_rejected_key_from_the_model_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no key route, the authenticated model list is what surfaces a bad key."""

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "wrong-key")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-medium-2604")
    monkeypatch.setattr(reporting.status.httpx, "AsyncClient", FakeStatusClient)
    FakeStatusClient.gets = []
    FakeStatusClient.responses = {
        "https://api.mistral.ai/v1/models": FakeResponse(401, {"message": "Unauthorized"}),
    }

    status = asyncio.run(check_provider_status(create_mistral_resolver().resolve()))

    assert status.reachable is False and status.reason == "invalid-api-key"


def test_status_check_still_probes_the_key_route_for_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.status.httpx, "AsyncClient", FakeStatusClient)
    FakeStatusClient.gets = []
    FakeStatusClient.responses = {
        "https://openrouter.ai/api/v1/key": FakeResponse(200, {"data": {"label": "unit-test"}}),
        "https://openrouter.ai/api/v1/models": FakeResponse(200, {"data": [{"id": "gpt-test"}]}),
    }

    status = asyncio.run(check_provider_status(create_openrouter_resolver().resolve()))

    assert status.reachable is True
    assert FakeStatusClient.gets == [
        "https://openrouter.ai/api/v1/key",
        "https://openrouter.ai/api/v1/models",
    ]


def clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MISTRAL_API_KEY",
        "MISTRAL_MODEL",
        "MISTRAL_BASE_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


class FakeClock:
    """Monotonic clock that only advances when the test says so.

    Lets the budget tests assert exactly which attempts are skipped without
    depending on real elapsed time, which would make them slow and flaky.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def install_fake_clock(monkeypatch: pytest.MonkeyPatch, seconds_per_request: float) -> FakeClock:
    """Advance the client's clock by a fixed amount on every outbound POST."""

    clock = FakeClock()
    monkeypatch.setattr(reporting.client.time, "perf_counter", clock)

    async def slow_post(self, *args, **kwargs):
        FakeAsyncClient.posts.append({"args": args, "kwargs": kwargs})
        clock.now += seconds_per_request
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(FakeAsyncClient, "post", slow_post)
    # Backoff sleeps are real time we don't want to spend in tests; the budget
    # arithmetic under test uses the fake clock, not the sleep.
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(reporting.client.asyncio, "sleep", no_sleep)
    return clock


def assert_fallback_report(report, expected_reason: str) -> None:
    payload = report.model_dump(by_alias=True)

    assert payload["reportMetadata"]["mode"] == "deterministic-fallback"
    assert payload["reportMetadata"]["fallbackReason"] == expected_reason


def test_generate_case_report_uses_fallback_when_llm_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert_fallback_report(report, "llm-not-configured")


def test_generate_case_report_uses_fallback_when_model_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no code-level default model: an API key alone is not enough."""

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert_fallback_report(report, "llm-not-configured")


def test_mistral_resolver_targets_the_mistral_chat_completions_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "unit-test-key")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-medium-2604")

    config = create_mistral_resolver().resolve()

    assert config is not None
    assert config.provider == "mistral"
    assert config.url == "https://api.mistral.ai/v1/chat/completions"
    assert config.model == "mistral-medium-2604"
    assert auth_headers(config) == {"Authorization": "Bearer unit-test-key"}


def test_default_resolver_prefers_mistral_over_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mistral is the default provider: it wins whenever both are configured."""

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-medium-2604")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")

    config = create_default_resolver().resolve()

    assert config is not None and config.provider == "mistral"


def test_default_resolver_falls_back_to_openrouter_when_mistral_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")

    config = create_default_resolver().resolve()

    assert config is not None and config.provider == "openrouter"


def test_default_resolver_returns_none_when_no_provider_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)

    assert create_default_resolver().resolve() is None


def test_generate_case_report_uses_mistral_when_its_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: the default provider is reflected in the report's audit trace."""

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "unit-test-key")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-medium-2604")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    FakeAsyncClient.responses = [
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "The mask covers 12.5% of the image for engineering review.",
                                    "observations": ["Predicted lesion area is 12.5% of the image."],
                                    "qualityChecks": ["Confirm the mask boundary against the dermoscopy image."],
                                }
                            )
                        },
                    }
                ]
            },
        )
    ]

    report = asyncio.run(generate_case_report(CaseReportRequest()))
    payload = report.model_dump(by_alias=True)

    assert payload["reportMetadata"]["mode"] == "llm"
    assert payload["reportMetadata"]["provider"] == "mistral"
    assert payload["reportMetadata"]["model"] == "mistral-medium-2604"
    assert FakeAsyncClient.posts[0]["args"][0] == "https://api.mistral.ai/v1/chat/completions"


def test_generate_case_report_returns_llm_report_when_provider_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    FakeAsyncClient.responses = [
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "The mask covers 12.5% of the image for engineering review.",
                                    "observations": ["Predicted lesion area is 12.5%."],
                                    "qualityChecks": ["Inspect the overlay against the source image."],
                                }
                            )
                        },
                    }
                ]
            },
        )
    ]

    report = asyncio.run(
        generate_case_report(CaseReportRequest.model_validate({"metrics": {"predAreaPct": 12.5}}))
    )
    payload = report.model_dump(by_alias=True)
    posted_body = FakeAsyncClient.posts[0]["kwargs"]["json"]

    assert payload["reportMetadata"]["mode"] == "llm"
    assert payload["reportMetadata"]["provider"] == "openrouter"
    assert payload["summary"] == "The mask covers 12.5% of the image for engineering review."
    assert posted_body["response_format"]["type"] == "json_object"  # OpenRouter is hardcoded non-strict
    assert posted_body["messages"][1]["role"] == "user"


def test_mistral_structured_outputs_sends_strict_schema_on_the_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "unit-test-key")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-medium-2604")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    FakeAsyncClient.responses = [
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "The mask covers 12.5% of the image for engineering review.",
                                    "observations": ["Predicted lesion area is 12.5%."],
                                    "qualityChecks": ["Inspect the overlay against the source image."],
                                }
                            )
                        },
                    }
                ]
            },
        )
    ]

    asyncio.run(generate_case_report(CaseReportRequest.model_validate({"metrics": {"predAreaPct": 12.5}})))
    posted_body = FakeAsyncClient.posts[0]["kwargs"]["json"]

    response_format = posted_body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["name"] == REPORT_SCHEMA_NAME
    assert response_format["json_schema"]["schema"] == REPORT_JSON_SCHEMA
    # The contract must still be described in the prompt: strict mode ignores
    # the length and item-count bounds that outputContract carries.
    assert json.loads(posted_body["messages"][1]["content"])["outputContract"] == REPORT_JSON_SCHEMA


@pytest.mark.parametrize(
    ("fake_response", "expected_reason"),
    [
        (httpx.TimeoutException("timed out"), "llm-timeout"),
        (httpx.HTTPError("network failed"), "llm-network-error"),
        (FakeResponse(401, {"error": {"message": "unauthorized"}}), "llm-http-401"),
        (FakeResponse(200, {"choices": []}), "llm-empty-response"),
        (
            FakeResponse(
                200,
                {"choices": [{"message": {"content": "not valid json"}}]},
            ),
            "llm-invalid-json",
        ),
        # Well-formed JSON that ignores the contract: an extra key, which
        # extra="forbid" rejects. This is the failure mode strict structured
        # outputs is meant to make unrepresentable, so pin it end to end.
        (
            FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "Mask covers a small lesion region.",
                                        "observations": ["Predicted lesion area is 12.5%."],
                                        "qualityChecks": ["Inspect the overlay."],
                                        "confidence": 0.92,
                                    }
                                )
                            }
                        }
                    ]
                },
            ),
            "llm-invalid-json",
        ),
        # A non-JSON envelope is a different failure from non-JSON content:
        # nothing in front of the model produced this, so it gets its own slug
        # rather than blaming the model for a gateway's HTML error page.
        (
            NonJsonResponse("<html><body>502 Bad Gateway</body></html>"),
            "llm-invalid-response",
        ),
    ],
)
def test_generate_case_report_uses_fallback_for_llm_failures(
    monkeypatch: pytest.MonkeyPatch,
    fake_response: FakeResponse | Exception,
    expected_reason: str,
) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    FakeAsyncClient.responses = [fake_response]

    settings = reporting.client.GenerationSettings(
        attempt_timeout_seconds=reporting.client.DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        max_retries=0,
        max_output_tokens=reporting.client.DEFAULT_MAX_OUTPUT_TOKENS,
    )
    report = asyncio.run(CaseReportGenerator(settings=settings).generate(CaseReportRequest()))

    assert_fallback_report(report, expected_reason)
    assert len(FakeAsyncClient.posts) == 1


VALID_REPORT_CONTENT = {
    "summary": "The mask covers 12.5% of the image for engineering review.",
    "observations": ["Predicted lesion area is 12.5%."],
    "qualityChecks": ["Inspect the overlay against the source image."],
}


def content_response(content: str | dict) -> FakeResponse:
    """Wrap message content in the chat-completion envelope the parser expects."""

    body = content if isinstance(content, str) else json.dumps(content)
    return FakeResponse(200, {"choices": [{"message": {"content": body}}]})


def install_llm_provider(monkeypatch: pytest.MonkeyPatch, responses: list) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    FakeAsyncClient.responses = responses


def test_invalid_payload_is_retried_and_a_valid_resample_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """A contract-violating payload is a bad sample, not a bad request.

    The status code is 200, so the retry loop used to return immediately and
    turn one unlucky sample into a user-visible fallback while two budgeted
    attempts went unused.
    """

    install_llm_provider(
        monkeypatch,
        [
            content_response({**VALID_REPORT_CONTENT, "confidence": 0.92}),
            content_response(VALID_REPORT_CONTENT),
        ],
    )

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert report.report_metadata.mode == "llm"
    assert report.report_metadata.fallback_reason is None
    assert len(FakeAsyncClient.posts) == 2


def test_refusal_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resampling does not change a decision the model made about the prompt."""

    install_llm_provider(
        monkeypatch,
        [
            FakeResponse(200, {"choices": [{"message": {"refusal": "I cannot help with that."}}]}),
            content_response(VALID_REPORT_CONTENT),
        ],
    )

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert_fallback_report(report, "llm-refusal")
    assert len(FakeAsyncClient.posts) == 1


def test_invalid_payload_logging_identifies_the_broken_contract_rule(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`llm-invalid-json` covers every contract breach, so the log must say which.

    Without the response body in the record there is no way to tell a renamed
    key from an over-long field from a preamble before the JSON.
    """

    over_long_observation = "x" * 300
    install_llm_provider(
        monkeypatch,
        [content_response({**VALID_REPORT_CONTENT, "observations": [over_long_observation]})] * 3,
    )

    with caplog.at_level(logging.WARNING, logger="reporting.client"):
        report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert_fallback_report(report, "llm-invalid-json")
    detail = next(
        record.getMessage() for record in caplog.records if "reason=llm-invalid-json" in record.getMessage()
    )
    assert "model=gpt-test" in detail
    assert "observations" in detail
    assert over_long_observation[:50] in detail


def test_rate_limit_logging_carries_the_body_and_retry_after(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A 429 says nothing on its own: per-minute and per-day look identical.

    The body is where the provider explains which limit was hit, so it must
    reach the log — diagnosing the live 429s from the status code alone was
    guesswork.
    """

    rate_limited = FakeResponse(
        429,
        {"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}},
        headers={"Retry-After": "1"},
    )
    install_llm_provider(monkeypatch, [rate_limited, content_response(VALID_REPORT_CONTENT)])

    with caplog.at_level(logging.WARNING, logger="reporting.client"):
        report = asyncio.run(generate_case_report(CaseReportRequest()))

    rejected = next(record.getMessage() for record in caplog.records if "rejected" in record.getMessage())
    assert "status=429" in rejected
    assert "free-models-per-day" in rejected
    assert "retry_after=1.0" in rejected
    # Retrying was still correct here: the provider named a wait we could afford.
    assert report.report_metadata.mode == "llm"


def test_retry_after_is_respected_instead_of_the_shorter_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backoff is a guess; Retry-After is the provider stating the answer.

    Regression: the exponential schedule put all three attempts inside one
    second, which cannot clear a limit that resets in sixty and spends the
    quota trying.
    """

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    install_llm_provider(
        monkeypatch,
        [
            FakeResponse(429, {"error": "slow down"}, headers={"Retry-After": "8"}),
            content_response(VALID_REPORT_CONTENT),
        ],
    )
    monkeypatch.setattr(reporting.client.asyncio, "sleep", fake_sleep)

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert slept == [8.0]  # not the 0.25s first exponential step
    assert report.report_metadata.mode == "llm"


def test_retry_stops_when_retry_after_exceeds_the_remaining_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Waiting past the deadline helps nobody: fall back now, not in 90s."""

    install_llm_provider(
        monkeypatch,
        [FakeResponse(429, {"error": "daily limit"}, headers={"Retry-After": "90"})] * 3,
    )

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert_fallback_report(report, "llm-http-429")
    assert len(FakeAsyncClient.posts) == 1


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("3", 3.0),
        ("0.5", 0.5),
        ("-5", 0.0),
        ("not-a-date", None),
        (None, None),
    ],
)
def test_retry_after_parsing(header: str | None, expected: float | None) -> None:
    response = FakeResponse(429, {}, headers={"Retry-After": header} if header else None)

    assert reporting.client.retry_after_seconds(response) == expected


def test_retry_after_accepts_an_http_date() -> None:
    """RFC 7231 allows either seconds or a date, and providers use both."""

    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    response = FakeResponse(429, {}, headers={"Retry-After": format_datetime(future, usegmt=True)})

    seconds = reporting.client.retry_after_seconds(response)

    assert seconds is not None
    assert 25 <= seconds <= 31


def test_every_unusable_response_is_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """A refusal used to fail silently: the slug reached the UI, nothing reached the log."""

    install_llm_provider(
        monkeypatch,
        [FakeResponse(200, {"choices": [{"message": {"refusal": "I will not diagnose."}}]})],
    )

    with caplog.at_level(logging.WARNING, logger="reporting.client"):
        report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert_fallback_report(report, "llm-refusal")
    logged = next(record.getMessage() for record in caplog.records if "reason=llm-refusal" in record.getMessage())
    assert "I will not diagnose." in logged


def test_response_body_text_survives_an_unreadable_body() -> None:
    """A logging helper that raises would hide the error it was added to explain."""

    class ExplodingResponse:
        status_code = 500
        headers: dict = {}

        @property
        def text(self) -> str:
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")

    assert "unreadable body" in reporting.util.response_body_text(ExplodingResponse())


def test_collapse_for_log_flattens_whitespace_without_dropping_anything() -> None:
    assert reporting.util.collapse_for_log("a\n  b\tc") == "a b c"

    long_text = "y" * 500
    assert reporting.util.collapse_for_log(long_text) == long_text


def test_total_budget_stops_retrying_before_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retry loop must not run attempts that outlive the total budget.

    Without deadline-gating the loop always burns all three attempts, which is
    what let the Python side outlive the Express deadline and turn a usable
    fallback report into a 504.
    """

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    install_fake_clock(monkeypatch, seconds_per_request=25.0)

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert_fallback_report(report, "llm-timeout")
    # Third attempt would start at t=50s, past the 40s budget.
    assert len(FakeAsyncClient.posts) == 2


def test_no_attempt_is_made_when_the_budget_is_already_too_small(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    install_fake_clock(monkeypatch, seconds_per_request=25.0)

    settings = reporting.client.GenerationSettings(
        attempt_timeout_seconds=reporting.client.DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        max_retries=reporting.client.DEFAULT_MAX_RETRIES,
        max_output_tokens=reporting.client.DEFAULT_MAX_OUTPUT_TOKENS,
        total_budget_seconds=0.5,
    )
    report = asyncio.run(CaseReportGenerator(settings=settings).generate(CaseReportRequest()))

    assert report.report_metadata.mode == "deterministic-fallback"
    assert FakeAsyncClient.posts == []


def test_fallback_report_records_the_time_the_llm_path_burned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: fallbacks used to report 0ms however long the LLM took."""

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    install_fake_clock(monkeypatch, seconds_per_request=25.0)

    report = asyncio.run(generate_case_report(CaseReportRequest()))

    assert report.report_metadata.latency_ms == 50_000


def test_a_single_slow_attempt_cannot_outlive_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hanging request must be cut off by the budget, not just retries.

    Regression: httpx timeouts bound the gap between bytes rather than elapsed
    wall clock, so a slow-trickling response ran 24s through a 5s read timeout
    in a live check. Only an explicit wall-clock deadline enforces the budget.
    """

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "gpt-test")
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []

    async def hanging_post(self, *args, **kwargs):
        FakeAsyncClient.posts.append({"args": args, "kwargs": kwargs})
        await asyncio.sleep(30)  # never completes within the budget
        raise AssertionError("request should have been cut off by the budget")

    monkeypatch.setattr(FakeAsyncClient, "post", hanging_post)

    # Above MIN_ATTEMPT_SECONDS so an attempt actually starts, but small
    # enough that the deadline fires quickly.
    settings = reporting.client.GenerationSettings(
        attempt_timeout_seconds=reporting.client.DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        max_retries=0,
        max_output_tokens=reporting.client.DEFAULT_MAX_OUTPUT_TOKENS,
        total_budget_seconds=2.5,
    )
    started = time.perf_counter()
    report = asyncio.run(CaseReportGenerator(settings=settings).generate(CaseReportRequest()))
    elapsed = time.perf_counter() - started

    assert_fallback_report(report, "llm-timeout")
    assert len(FakeAsyncClient.posts) == 1
    assert elapsed < 5, f"budget not enforced; took {elapsed:.1f}s"


def test_default_timeout_ordering_is_connect_le_silence_lt_attempt_le_budget() -> None:
    settings = reporting.client.GenerationSettings(
        attempt_timeout_seconds=reporting.client.DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        max_retries=reporting.client.DEFAULT_MAX_RETRIES,
        max_output_tokens=reporting.client.DEFAULT_MAX_OUTPUT_TOKENS,
    )
    assert (
        settings.connect_timeout_seconds
        <= settings.silence_timeout_seconds
        < settings.attempt_timeout_seconds
        <= settings.total_budget_seconds
    )


async def _serve_silence_then_body(host: str, think_seconds: float) -> tuple[asyncio.AbstractServer, int]:
    """A minimal HTTP/1.1 server: reads the request, is silent, then answers.

    Models a non-streaming LLM provider: the whole reply is generated first
    (silence, from the client's point of view), then sent as one chunk. This
    is the realistic slow-provider shape used to measure Phase C3 in
    kind-munching-papert-evidence/realistic_slow.py.
    """

    body = b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}'

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(65536)
        try:
            await asyncio.sleep(think_seconds)
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"\r\n"
                + body
            )
            await writer.drain()
            writer.close()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass

    server = await asyncio.start_server(handler, host, 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


def test_silence_timeout_restores_the_read_timeout_diagnostic(caplog: pytest.LogCaptureFixture) -> None:
    """Regression for the collision this phase fixes.

    Before this change, `asyncio.wait_for(timeout=left)` and httpx's own
    timeout became numerically equal on any budget-constrained attempt, and
    wait_for's earlier-started clock always won — so every non-final attempt
    against a stalled provider logged the generic ``TimeoutError`` instead of
    httpx's more specific ``ReadTimeout``. Measured directly against a real
    server that stays silent past the silence limit but within the attempt
    limit, using scaled settings (silence 1s, attempt 3s, budget 8s) so this
    runs in seconds. See stall_vs_attempt.py in
    kind-munching-papert-evidence/ for the same measurement at production
    scale.
    """

    async def run() -> reporting.client.GenerationResult:
        server, port = await _serve_silence_then_body("127.0.0.1", think_seconds=5.0)
        provider = ProviderConfig(
            provider="mistral",
            model="test-model",
            api_key=SecretStr("test-key"),
            url=f"http://127.0.0.1:{port}/v1/chat/completions",
            base_url=f"http://127.0.0.1:{port}/v1",
            response_format={},
        )
        settings = reporting.client.GenerationSettings(
            attempt_timeout_seconds=3.0,
            silence_timeout_seconds=1.0,
            connect_timeout_seconds=1.0,
            max_retries=2,
            max_output_tokens=700,
            total_budget_seconds=8.0,
        )
        async with server:
            return await reporting.client.LlmReportClient(
                provider=provider, settings=settings
            ).generate(CaseReportRequest(metrics=reporting.CaseMetrics(pred_area_pct=18.4)))

    with caplog.at_level(logging.WARNING, logger="reporting.client"):
        result = asyncio.run(run())

    assert result.fallback_reason == "llm-timeout"
    timeout_errors = [
        record.getMessage().rsplit("error=", 1)[-1]
        for record in caplog.records
        if "LLM report request timed out" in record.getMessage()
    ]
    assert "ReadTimeout" in timeout_errors, (
        f"expected at least one ReadTimeout among non-final attempts, got {timeout_errors}"
    )


def test_attempt_timeout_still_bounds_a_trickling_response(caplog: pytest.LogCaptureFixture) -> None:
    """The silence timeout does nothing against a body that dribbles without
    ever going silent that long — only asyncio.wait_for (attempt_timeout_seconds,
    clamped by the remaining budget) bounds that case. Confirms Phase C3 did
    not regress the guarantee test_a_single_slow_attempt_cannot_outlive_the_budget
    already covers with a fake client, here against a real trickling server.
    """

    async def trickle_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(65536)
        chunks = [b'{"choices":[{"message":{"content":"', *([b"xxxx"] * 20), b'"}}]}']
        n = sum(len(c) for c in chunks)
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {n}\r\n".encode()
            + b"\r\n"
        )
        await writer.drain()
        try:
            for chunk in chunks:
                writer.write(chunk)
                await writer.drain()
                await asyncio.sleep(0.3)  # no single gap exceeds the silence limit
            writer.close()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass

    async def run() -> tuple[reporting.client.GenerationResult, float]:
        server = await asyncio.start_server(trickle_handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        provider = ProviderConfig(
            provider="mistral",
            model="test-model",
            api_key=SecretStr("test-key"),
            url=f"http://127.0.0.1:{port}/v1/chat/completions",
            base_url=f"http://127.0.0.1:{port}/v1",
            response_format={},
        )
        settings = reporting.client.GenerationSettings(
            attempt_timeout_seconds=3.0,
            silence_timeout_seconds=1.0,
            connect_timeout_seconds=1.0,
            max_retries=0,
            max_output_tokens=700,
            total_budget_seconds=8.0,
        )
        started = time.perf_counter()
        async with server:
            result = await reporting.client.LlmReportClient(
                provider=provider, settings=settings
            ).generate(CaseReportRequest(metrics=reporting.CaseMetrics(pred_area_pct=18.4)))
        return result, time.perf_counter() - started

    result, elapsed = asyncio.run(run())

    assert result.fallback_reason == "llm-timeout"
    # Cut at ~attempt_timeout_seconds (3s), not left to run the full ~6s trickle.
    assert elapsed < 4.5, f"trickling response was not bounded by attempt_timeout_seconds; took {elapsed:.2f}s"


def test_case_report_generator_uses_injected_provider_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setattr(reporting.client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.posts = []
    FakeAsyncClient.responses = [
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Injected provider was used.",
                                    "observations": ["Predicted lesion area is 12.5%."],
                                    "qualityChecks": ["Inspect the overlay against the source image."],
                                }
                            )
                        },
                    }
                ]
            },
        )
    ]

    class FakeProviderResolver:
        def resolve(self) -> ProviderConfig:
            return ProviderConfig(
                provider="openrouter",
                url="https://example.test/chat/completions",
                base_url="https://example.test",
                model="fake-model",
                api_key=SecretStr("test-key"),
                response_format={"type": "json_object"},
            )

    generator = CaseReportGenerator(provider_resolver=FakeProviderResolver())
    report = asyncio.run(generator.generate(CaseReportRequest()))
    payload = report.model_dump(by_alias=True)

    assert payload["reportMetadata"]["mode"] == "llm"
    assert payload["reportMetadata"]["model"] == "fake-model"
    assert FakeAsyncClient.posts[0]["args"][0] == "https://example.test/chat/completions"
