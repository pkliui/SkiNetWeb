"""Provider health checking, independent of report generation.
"""

import logging

import httpx

from .models import ProviderStatus
from .provider import ProviderConfig, auth_headers
from .util import collapse_for_log, response_body_text

logger = logging.getLogger(__name__)

DEFAULT_STATUS_CHECK_TIMEOUT_SECONDS = 5.0


async def check_provider_status(provider: ProviderConfig) -> ProviderStatus:
    """Validate the configured API key and model against the provider.

    Runs up to two checks in sequence, short-circuiting on the first
    failure:

    1. ``GET {provider.key_check_path}`` confirms the API key is valid (a
       401 response means it isn't). Skipped when the provider exposes no
       such route (``key_check_path is None``, e.g. Mistral) — probing
       OpenRouter's ``/key`` path on such a provider would 404 and be
       misreported as an outage. The model list request in step 2 is itself
       authenticated, so a bad key still surfaces there as a 401; only the
       extra precision of distinguishing "key is bad" from "model list is
       unavailable" is lost.
    2. ``GET /models`` confirms ``provider.model`` is one the provider
       actually serves. This catches a mistyped or discontinued
       ``{PREFIX}_MODEL`` before it fails on a real report request.

    ``/key`` and ``/models`` are used rather than ``/chat/completions`` so
    that status checks don't spend tokens or count as generation traffic
    against the account quota — this function is meant to be polled on
    demand, e.g. from a health-check UI or monitoring probe.

    Deliberately builds its own short-lived client rather than borrowing the
    pooled one the app hands to report generation: an on-demand probe is
    rare enough that pooling buys nothing, and keeping it off that client
    means a hung status check cannot occupy a connection the report path
    needs while racing its deadline.

    Args:
        provider: The provider configuration to validate.

    Returns:
        A :class:`ProviderStatus` describing whether the provider is
        configured, reachable, and — on failure — why not.
    """

    # Every exit below reports a configured provider, so only `reachable` and
    # `reason` actually vary; naming that once keeps the differences visible.
    def status(*, reachable: bool, reason: str | None = None) -> ProviderStatus:
        return ProviderStatus(llmConfigured=True, reachable=reachable, reason=reason)

    base_url = provider.base_url
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_STATUS_CHECK_TIMEOUT_SECONDS) as client:
            if provider.key_check_path is not None:
                key_response = await client.get(
                    f"{base_url}/{provider.key_check_path.lstrip('/')}", headers=auth_headers(provider)
                )
                if key_response.status_code != 200:
                    logger.warning(
                        "LLM provider key check failed provider=%s status=%s body=%s",
                        provider.provider,
                        key_response.status_code,
                        collapse_for_log(response_body_text(key_response)),
                    )
                    if key_response.status_code == 401:
                        return status(reachable=False, reason="invalid-api-key")
                    return status(reachable=False, reason=f"http-{key_response.status_code}")

            models_response = await client.get(f"{base_url}/models", headers=auth_headers(provider))
    except httpx.HTTPError as exc:
        logger.warning("LLM provider status check failed provider=%s error=%s", provider.provider, exc)
        return status(reachable=False, reason="network-error")

    if models_response.status_code != 200:
        logger.warning(
            "LLM provider model list check failed provider=%s status=%s",
            provider.provider,
            models_response.status_code,
        )
        # A 401 here is unambiguous regardless of which checks ran: the
        # credential was rejected. Without this, a provider that skips the
        # key check (see above) would report a bad key as merely
        # "model-check-failed" — and, worse, as reachable.
        if models_response.status_code == 401:
            return status(reachable=False, reason="invalid-api-key")
        # The API key is valid and the provider is reachable; a failed
        # model-list fetch alone shouldn't report the provider as down.
        return status(reachable=True, reason="model-check-failed")

    try:
        available_models = {
            entry.get("id") for entry in (models_response.json().get("data") or []) if isinstance(entry, dict)
        }
    except ValueError as exc:
        logger.warning(
            "LLM provider model list was not JSON provider=%s error=%s body=%s",
            provider.provider,
            exc,
            collapse_for_log(response_body_text(models_response)),
        )
        return status(reachable=True, reason="model-check-failed")

    if provider.model not in available_models:
        logger.warning(
            "Configured model is not served by the provider provider=%s model=%s",
            provider.provider,
            provider.model,
        )
        return status(reachable=False, reason="invalid-model")

    return status(reachable=True)
