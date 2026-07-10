import json

import pytest
from pydantic import ValidationError

from reporting import (
    CaseReportRequest,
    LlmReportPayload,
    ProviderConfig,
    build_fallback_report,
    build_report_prompt,
    normalise_json_content,
    payload_to_report,
    should_retry,
)


def test_case_report_request_accepts_camel_case_metrics() -> None:
    request = CaseReportRequest.model_validate(
        {
            "fileName": "case.png",
            "imageType": "image/png",
            "imageSizeBytes": 1234,
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

    assert payload["promptTrace"]["mode"] == "deterministic-fallback"
    assert payload["promptTrace"]["fallbackReason"] == "unit-test"
    assert payload["promptTrace"]["latencyMs"] == 7
    assert payload["qualityChecks"][0].startswith("Very small predicted area")


def test_prompt_is_compact_json_and_preserves_metric_alias() -> None:
    request = CaseReportRequest.model_validate({"metrics": {"predAreaPct": 42.0}})
    prompt = json.loads(build_report_prompt(request))

    assert prompt["metrics"]["predAreaPct"] == 42.0
    assert "requirements" in prompt
    assert "diagnosis" in " ".join(prompt["requirements"])
    assert prompt["metrics"] == {"predAreaPct": 42.0}


def test_normalise_json_content_accepts_markdown_fence() -> None:
    content = '```json\n{"summary":"ok"}\n```'

    assert normalise_json_content(content) == '{"summary":"ok"}'


def test_retry_policy_only_retries_rate_limits_and_server_errors() -> None:
    assert should_retry(429)
    assert should_retry(500)
    assert should_retry(503)
    assert not should_retry(400)
    assert not should_retry(401)


def test_fallback_report_is_truthful_when_metrics_are_missing() -> None:
    report = build_fallback_report(CaseReportRequest(), reason="unit-test")
    payload = report.model_dump(by_alias=True)

    assert "not available" in payload["summary"]
    assert payload["qualityChecks"][0] == "Segmentation metrics were not supplied with this report request."


def test_llm_payload_rejects_empty_report_items() -> None:
    with pytest.raises(ValidationError):
        LlmReportPayload.model_validate({"summary": "ok", "observations": [""]})


def test_payload_to_report_records_llm_trace() -> None:
    provider = ProviderConfig(
        provider="openai",
        url="https://example.test",
        model="gpt-test",
        headers={},
        body_fields={"model": "gpt-test"},
    )
    payload = LlmReportPayload.model_validate({"summary": "Mask covers a small lesion region."})

    report = payload_to_report(payload, provider=provider, latency_ms=12).model_dump(by_alias=True)

    assert report["promptTrace"]["mode"] == "llm"
    assert report["promptTrace"]["model"] == "gpt-test"
    assert report["observations"] == ["The model returned a summary without detailed observations."]
