"""Small helpers shared across the reporting layers: safe response logging.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


def response_body_text(response: httpx.Response) -> str:
    """Get a response's body as text, safely, for use in a log message.

    ``response.text`` can itself raise (e.g. a cut-off or mislabelled body),
    and that would crash the very log line meant to explain the original
    error. So on failure this returns a placeholder string instead of
    raising.

    Args:
        response: The HTTP response to read.

    Returns:
        The body as text, or a placeholder describing why it couldn't be
        read.
    """

    try:
        return response.text
    except Exception as exc:  # noqa: BLE001 - a logging helper must not raise
        return f"<unreadable body: {type(exc).__name__}: {exc}>"


def collapse_for_log(text: str) -> str:
    """Flatten ``text`` to a single line, for log output.

    Multi-line diagnostics (a pydantic error, a raw model response) are
    collapsed to one line since a log record spanning many lines is hard to
    read. The full text is kept — nothing is cut — so no part of the
    diagnostic is lost.

    Args:
        text: The text to collapse.
    """

    return " ".join(text.split())
