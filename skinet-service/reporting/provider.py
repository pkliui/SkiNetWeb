"""Resolves LLM provider configuration from environment variables.

Two-stage pipeline: `ProviderEnvSettings` is a raw, unvalidated read of the
env vars; `EnvironmentProviderResolver.resolve()` turns it into a
`ProviderConfig` — immutable, and only ever valid, or `None`. Get an
instance via `create_mistral_resolver` / `create_openrouter_resolver`, or
normally `create_default_resolver` (Mistral first, OpenRouter fallback),
rather than constructing `EnvironmentProviderResolver` directly.
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import JSON_OBJECT_RESPONSE_FORMAT, STRICT_JSON_SCHEMA_RESPONSE_FORMAT

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

ProviderName = Literal["mistral", "openrouter"]


class ProviderEnvSettings(BaseSettings):
    """Raw, unvalidated read of the 3 env vars for one provider, by fixed
    name under a caller-supplied prefix (e.g. `MISTRAL_API_KEY` for
    `prefix="MISTRAL"`). Feeds `EnvironmentProviderResolver.resolve()`,
    which turns it into a validated `ProviderConfig` or `None`.

    Built fresh on every `resolve()` call — `BaseSettings` reads
    `os.environ` at construction time, so each instance reflects the
    environment as it currently is.
    """

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None

    @field_validator("api_key", "model", "base_url", mode="before")
    @classmethod
    def _strip_blank_to_none(cls, v: object) -> str | None:
        """Blank == unset."""
        return _blank_to_none(None if v is None else str(v))


@dataclass(frozen=True)
class ProviderConfig:
    """Validated, ready-to-use chat-completion config for one provider.

    Produced only by a successful `ProviderResolver.resolve()` — there's no
    invalid `ProviderConfig`, so consumers never re-check it. Frozen so it's
    safe to share read-only across a request's lifetime.

    Attributes:
        provider: Provider name.
        url: Full chat-completions endpoint URL.
        base_url: The provider's base URL (no trailing slash), i.e. `url`
            with `chat_completions_path` removed. Kept alongside `url`
            rather than derived from it, so consumers hitting other
            endpoints (e.g. `check_provider_status` probing `/models`)
            don't have to reconstruct it by string-splitting `url`.
        model: Model identifier to request.
        api_key: Credential, as `SecretStr` so it can't leak via `repr`/`str`;
            `auth_headers()` unwraps it fresh at request time instead of it
            being precomputed here.
        key_check_path: Cheap authenticated GET path for validating the key
            without spending tokens. `None` if the provider has none
            (Mistral) — `check_provider_status` then infers key validity
            from the model-list call it makes anyway.
        response_format: `STRICT_JSON_SCHEMA_RESPONSE_FORMAT` or
            `JSON_OBJECT_RESPONSE_FORMAT` (see `_resolve_response_format`).
            `LlmReportSchema` still validates the response either way.
    """

    provider: ProviderName
    url: str
    base_url: str
    model: str
    api_key: SecretStr
    response_format: Mapping[str, Any]
    key_check_path: str | None = "key"


def auth_headers(config: ProviderConfig) -> dict[str, str]:
    """Compose request headers for `config`, unwrapping the API key here
    rather than storing it precomputed on `ProviderConfig`, so the plaintext
    key exists only as a local value at request time.

    Both providers are OpenAI-shaped: `Authorization: Bearer <key>`.

    Returns:
        The auth header.
    """

    return {"Authorization": f"Bearer {config.api_key.get_secret_value()}"}


class ProviderResolver(Protocol):
    """Interface for resolving optional LLM provider configuration.

    Implementations determine the source of configuration (environment
    variables, a secrets manager, test fixtures, etc.). Callers should
    depend on this Protocol rather than a concrete implementation, so the
    configuration source can be changed without modifying call sites. See
    `EnvironmentProviderResolver` for the concrete, environment-variable-backed
    implementation used in production.
    """

    def resolve(self) -> ProviderConfig | None:
        """Resolve provider configuration.

        Returns:
            A ready-to-use `ProviderConfig`, or `None` if no working
            configuration can be produced. `None` covers both an absent
            configuration (e.g. local development or tests running without a
            provider) and an invalid one (e.g. a malformed base URL) —
            implementations should log a diagnostic for the latter case
            before returning `None`, so the cause is visible without raising.
            Callers are expected to treat both cases identically: check for
            `None` and handle "no provider available" explicitly, rather
            than via exception handling. Exceptions should be reserved for
            programming errors, not for runtime configuration problems.
        """
        ...


class EnvironmentProviderResolver:
    """Reads provider configuration from environment variables.

    Carries no assumptions about any specific provider — every provider-
    specific value (which env vars to read, what the default base URL is,
    what the chat-completions path looks like, which optional env vars map
    to which HTTP headers) is supplied by the caller at construction time.
    See `create_mistral_resolver` and `create_openrouter_resolver` for the
    provider-specific instances used in production.

    Env vars are named by `prefix`, e.g. with `prefix="OPENROUTER"`:
        OPENROUTER_API_KEY:  Required. Credential used to authenticate
            with the provider.
        OPENROUTER_MODEL:    Required. Model identifier to request.
        OPENROUTER_BASE_URL: Optional. Defaults to `default_base_url`. Must
            resolve to an https URL; see `resolve` for why.

    `structured_outputs` (constructor arg, not an env var) is a fixed fact
    about the provider/model — whether it honours strict `json_schema`
    decoding — set once by `create_mistral_resolver`/`create_openrouter_resolver`,
    not a per-deployment toggle.

    A second provider can be resolved by constructing another instance with
    different arguments — no subclass needed, as long as the provider is
    reachable via an OpenAI-style `POST {base_url}/{path}` call authenticated
    with `Authorization: Bearer <api_key>` (see `auth_headers`). A provider
    with a differently-shaped endpoint or auth scheme needs its own
    `ProviderResolver` implementation instead.
    """

    def __init__(
        self,
        provider: ProviderName,
        *,
        prefix: str,
        default_base_url: str,
        chat_completions_path: str,
        structured_outputs: bool,
        key_check_path: str | None = "key",
    ) -> None:
        self._provider = provider
        self._prefix = prefix
        self._default_base_url = default_base_url
        self._chat_completions_path = chat_completions_path
        self._structured_outputs = structured_outputs
        self._key_check_path = key_check_path

    def resolve(self) -> ProviderConfig | None:
        """Build a `ProviderConfig` from environment variables.

        Returns:
            A `ProviderConfig` if `{prefix}_API_KEY` and `{prefix}_MODEL` are
            both set, and `{prefix}_BASE_URL` (if provided) is a valid https
            URL. Otherwise `None`.

        A warning naming every missing or invalid variable is logged
        whenever `None` is returned, whether nothing is configured at all
        or only part of it is — so a fully-unconfigured fallback provider
        and a typo'd one are equally diagnosable from the logs.
        `{prefix}_BASE_URL` is restricted to https to prevent the API key
        from being sent in plaintext if the base URL is ever misconfigured
        to point at an http endpoint.

        A fresh `ProviderEnvSettings` is read on every call.
        """
        try:
            settings = ProviderEnvSettings(_env_prefix=f"{self._prefix}_")
        except ValidationError as exc:
            logger.warning(
                "%s configuration invalid: %s",
                self._provider,
                "; ".join(
                    f"{self._prefix}_{str(e['loc'][0]).upper()}={e['msg']}" for e in exc.errors()
                ),
            )
            return None

        missing = [
            f"{self._prefix}_{env_suffix}"
            for env_suffix, value in (("API_KEY", settings.api_key), ("MODEL", settings.model))
            if not value
        ]
        if missing:
            logger.warning("%s not configured: missing %s", self._provider, ", ".join(missing))
            return None

        base_url = settings.base_url or self._default_base_url
        parsed_base_url = urlparse(base_url)
        if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
            logger.warning(
                "Ignoring %s_BASE_URL=%r: must be an https URL with a host", self._prefix, base_url
            )
            return None

        base_url = base_url.rstrip("/")
        return ProviderConfig(
            provider=self._provider,
            url=f"{base_url}/{self._chat_completions_path.lstrip('/')}",
            base_url=base_url,
            model=settings.model,
            api_key=SecretStr(settings.api_key),
            response_format=_resolve_response_format(self._structured_outputs),
            key_check_path=self._key_check_path,
        )


def create_openrouter_resolver() -> EnvironmentProviderResolver:
    """Builds the `EnvironmentProviderResolver` configured for OpenRouter.

    This is the one place OpenRouter-specific values (env var prefix,
    default base URL, endpoint path) are set; the class itself stays
    provider-agnostic.

    `structured_outputs=False`: OpenRouter routes to an arbitrary,
    caller-chosen model, so strict `json_schema` support can't be assumed.

    Returns:
        An `EnvironmentProviderResolver` for OpenRouter, reading
        `OPENROUTER_*` environment variables.
    """

    return EnvironmentProviderResolver(
        "openrouter",
        prefix="OPENROUTER",
        default_base_url=DEFAULT_OPENROUTER_BASE_URL,
        chat_completions_path="chat/completions",
        structured_outputs=False,
    )


def create_mistral_resolver() -> EnvironmentProviderResolver:
    """Builds the `EnvironmentProviderResolver` configured for Mistral.

    Mistral's `/v1/chat/completions` endpoint is OpenAI-shaped — same body,
    same `Authorization: Bearer` header, same `response_format` — so it needs
    no client of its own and no vendor SDK: only the env-var prefix, base URL
    and endpoint path differ from OpenRouter.

    `structured_outputs=True`: `mistral-medium-2604` (Medium 3.5, the
    configured default) honours strict `json_schema`, verified against the
    live API.

    Returns:
        An `EnvironmentProviderResolver` for Mistral, reading `MISTRAL_*`
        environment variables.
    """

    return EnvironmentProviderResolver(
        "mistral",
        prefix="MISTRAL",
        default_base_url=DEFAULT_MISTRAL_BASE_URL,
        chat_completions_path="chat/completions",
        structured_outputs=True,
        key_check_path=None,
    )


class FirstConfiguredResolver:
    """Delegates to an ordered list of resolvers, taking the first that resolves.

    This is how the service expresses a *default* provider without hard-wiring
    one: the chain is tried in order, so whichever provider has its credentials
    present wins, and removing `MISTRAL_API_KEY` from an environment silently
    reverts it to OpenRouter with no code or image change. A resolver returning
    `None` covers both "not configured here" and "configured but invalid" (see
    `ProviderResolver.resolve`), and each already logs its own diagnostic, so
    the chain can treat the two the same and move on.
    """

    def __init__(self, resolvers: Sequence[ProviderResolver]) -> None:
        self._resolvers = tuple(resolvers)

    def resolve(self) -> ProviderConfig | None:
        for resolver in self._resolvers:
            config = resolver.resolve()
            if config is not None:
                return config
        return None


def create_default_resolver() -> FirstConfiguredResolver:
    """The production resolver: Mistral first, OpenRouter as the fallback.
    
    Returns:
        A `FirstConfiguredResolver` chaining the Mistral and OpenRouter
        resolvers, in that order.
    """

    return FirstConfiguredResolver((create_mistral_resolver(), create_openrouter_resolver()))


def _resolve_response_format(structured_outputs: bool) -> Mapping[str, Any]:
    """Choose the structured-output mode for a resolver's `structured_outputs` setting.

    Both constants are already immutable mappings, so the returned value is
    safe to share on the frozen `ProviderConfig` without copying.

    Args:
        structured_outputs: The resolver's `structured_outputs` constructor
            argument (see `create_mistral_resolver` / `create_openrouter_resolver`).

    Returns:
        `STRICT_JSON_SCHEMA_RESPONSE_FORMAT` if `structured_outputs` is
        `True`, otherwise `JSON_OBJECT_RESPONSE_FORMAT`.
    """

    return STRICT_JSON_SCHEMA_RESPONSE_FORMAT if structured_outputs else JSON_OBJECT_RESPONSE_FORMAT


def _blank_to_none(value: str | None) -> str | None:
    """Strip incidental whitespace and collapse a blank result to `None`.

    Values sourced from Kubernetes secret mounts or `.env` files commonly
    carry a trailing newline or leading/trailing spaces. Left unstripped,
    that whitespace would be silently embedded in a Bearer token or model
    name, causing authentication failures or model-not-found errors that
    are difficult to diagnose since the value looks correct when printed.

    Args:
        value: Raw string to clean, or `None`.

    Returns:
        The trimmed value, or `None` if `value` is `None` or its trimmed
        value is empty. Treating a blank string as `None` lets callers use
        a single truthiness check to detect "not configured", rather than
        checking for both `None` and `""` separately.
    """

    if value is None:
        return None
    value = value.strip()
    return value or None
