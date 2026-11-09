"""Deterministic fallback report construction when live LLM generation is unavailable."""

from .models import CaseMetrics, CaseReport, CaseReportRequest, ReportMetadata
from .prompt import CONTEXT, PROMPT_VERSION


class DeterministicReportBuilder:
    """Creates local reports when live LLM generation is unavailable."""

    def __init__(self, context: list[str] | None = None) -> None:
        self.context = context or CONTEXT

    def build(
        self,
        request: CaseReportRequest,
        *,
        latency_ms: int = 0,
        reason: str = "llm-not-configured",
    ) -> CaseReport:
        """Build a deterministic report from pre-computed segmentation metrics.

        Called from :meth:`CaseReportGenerator.generate` whenever the LLM
        path did not return a usable report.

        Args:
            request: The validated case report request.
            latency_ms: Wall-clock time already spent on a failed LLM
                attempt, recorded in the report's metadata rather than
                implying the fallback path is free.
            reason: Stable reason slug explaining why the LLM path was not
                used, recorded in the report's metadata.

        Returns:
            A :class:`CaseReport` built from ``request.metrics`` with no LLM
            call involved.
        """
        metrics = request.metrics
        area = f"{metrics.pred_area_pct:.1f}%" if metrics else "not available"
        has_ground_truth = bool(metrics and metrics.dice is not None and metrics.iou is not None)
        dice = f"{metrics.dice * 100:.1f}%" if metrics and metrics.dice is not None else "not supplied"
        iou = f"{metrics.iou * 100:.1f}%" if metrics and metrics.iou is not None else "not supplied"

        return CaseReport(
            summary=(
                f"Segmentation completed for {request.file_name or 'the uploaded dermoscopy image'} using SkiNet segmentation model "
                "trained on ISIC 2017 dataset. Predicted segmentation mask is shown in green. If user provided an ISIC 2017 test image "
                "available in EXAMPLES column, ground truth mask is shown in red. If user uploaded a photo, no ground truth is available. "
                "This report presents model output results and does not constitute a medical diagnosis."
            ),
            observations=[
                f"Predicted lesion area: {area}.",
                f"Ground-truth comparison is available: Dice {dice}, IoU {iou}."
                if has_ground_truth
                else "No ground-truth mask was supplied, so agreement metrics are unavailable.",
                "The segmentation mask can support measurement, review, and annotation workflows, but it should not be used alone for clinical decisions.",
            ],
            qualityChecks=quality_checks_for(metrics, has_ground_truth=has_ground_truth),
            reportMetadata=ReportMetadata(
                mode="deterministic-fallback",
                model="local-template",
                provider="local",
                promptVersion=PROMPT_VERSION,
                latencyMs=latency_ms,
                context=self.context,
                fallbackReason=reason,
            ),
        )


def quality_checks_for(metrics: CaseMetrics | None, *, has_ground_truth: bool) -> list[str]:
    """Derive deterministic engineering checks from segmentation metrics.

    Args:
        metrics: The case's segmentation metrics, or ``None`` if none were
            supplied.
        has_ground_truth: Whether Dice/IoU agreement metrics are available.

    Returns:
        A list of human-readable quality-check strings for the report.
    """

    if metrics is None:
        return [
            "Segmentation metrics were not supplied with this report request.",
            "Add a ground-truth mask to enable Dice, IoU, sensitivity, and specificity tracking.",
        ]

    area_check = (
        "Very small predicted area; verify that the lesion is visible and centered."
        if metrics.pred_area_pct < 1
        else "Predicted lesion area is present and measurable."
    )

    extreme_mask_check = (
        "Large predicted area; inspect for failed foreground/background separation."
        if metrics.pred_area_pct > 70
        else "No extreme full-image mask detected."
    )

    ground_truth_check = (
        "Ground-truth overlap metrics can be tracked in model evaluation dashboards."
        if has_ground_truth
        else "Add a ground-truth mask to enable Dice, IoU, sensitivity, and specificity tracking."
    )

    return [area_check, extreme_mask_check, ground_truth_check]


def build_fallback_report(
    request: CaseReportRequest,
    *,
    latency_ms: int = 0,
    reason: str = "llm-not-configured",
) -> CaseReport:
    """Create a deterministic report when the LLM is unavailable or invalid.

    Module-level convenience wrapper around a fresh
    :class:`DeterministicReportBuilder`.

    Args:
        request: The validated case report request.
        latency_ms: Wall-clock time already spent on a failed LLM attempt.
        reason: Stable reason slug explaining why the LLM path was not used.

    Returns:
        A :class:`CaseReport` built without an LLM call.
    """

    return DeterministicReportBuilder().build(request, latency_ms=latency_ms, reason=reason)
