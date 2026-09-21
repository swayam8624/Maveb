"""Implementation-backed analytic bounds used by the CBRC reference planner."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class GaussianPixelBound:
    before_opacity_mass: float
    after_opacity_mass: float
    termination_probability_bound: float
    rgb_linf_bound: float


@dataclass(frozen=True)
class TemporalBound:
    requires_hard_invalidation: bool
    retained_history_bound: float
    resolved_output_bound: float


def effective_gaussian_alpha(peak_opacity: float, squared_mahalanobis: float) -> float:
    """Mirror the production Metal compositor's alpha admission rules."""
    if not math.isfinite(peak_opacity) or not 0.0 <= peak_opacity <= 1.0:
        raise ValueError("peak_opacity must lie in [0,1]")
    if not math.isfinite(squared_mahalanobis) or squared_mahalanobis < 0.0:
        raise ValueError("squared_mahalanobis must be finite and non-negative")
    if squared_mahalanobis > 9.0:
        return 0.0
    alpha = min(0.99, peak_opacity * math.exp(-0.5 * squared_mahalanobis))
    return 0.0 if alpha < 1.0 / 255.0 else alpha


def opacity_mass(alphas: Iterable[float]) -> float:
    transmittance = 1.0
    for alpha in alphas:
        alpha = float(alpha)
        if not math.isfinite(alpha) or not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must lie in [0,1]")
        transmittance *= 1.0 - alpha
    return min(1.0, max(0.0, 1.0 - transmittance))


def gaussian_pixel_revision_bound(
    before_effective_alphas: Iterable[float],
    after_effective_alphas: Iterable[float],
    color_upper_bound: float,
) -> GaussianPixelBound:
    if not math.isfinite(color_upper_bound) or color_upper_bound < 0.0:
        raise ValueError("color_upper_bound must be finite and non-negative")
    before = opacity_mass(before_effective_alphas)
    after = opacity_mass(after_effective_alphas)
    termination = min(1.0, before + after)
    return GaussianPixelBound(
        before_opacity_mass=before,
        after_opacity_mass=after,
        termination_probability_bound=termination,
        rgb_linf_bound=color_upper_bound * termination,
    )


def temporal_revision_bound(
    *,
    current_error_bound: float,
    history_error_bound: float,
    neighborhood_extrema_error_bound: float,
    history_weight: float,
    validation_decision_stable: bool,
) -> TemporalBound:
    values = (
        current_error_bound,
        history_error_bound,
        neighborhood_extrema_error_bound,
    )
    if any((not math.isfinite(v) or v < 0.0) for v in values):
        raise ValueError("temporal error bounds must be finite and non-negative")
    if not math.isfinite(history_weight) or not 0.0 <= history_weight <= 1.0:
        raise ValueError("history_weight must lie in [0,1]")

    if not validation_decision_stable:
        return TemporalBound(
            requires_hard_invalidation=True,
            retained_history_bound=0.0,
            resolved_output_bound=current_error_bound,
        )

    retained = max(history_error_bound, neighborhood_extrema_error_bound)
    resolved = (1.0 - history_weight) * current_error_bound + history_weight * retained
    return TemporalBound(
        requires_hard_invalidation=False,
        retained_history_bound=retained,
        resolved_output_bound=resolved,
    )


def temporal_history_decay_bound(
    initial_history_error_bound: float, history_weight: float, frames: int
) -> float:
    if (
        not math.isfinite(initial_history_error_bound)
        or initial_history_error_bound < 0.0
    ):
        raise ValueError("initial history error must be finite and non-negative")
    if not math.isfinite(history_weight) or not 0.0 <= history_weight <= 1.0:
        raise ValueError("history_weight must lie in [0,1]")
    if frames < 0:
        raise ValueError("frames must be non-negative")
    return initial_history_error_bound * history_weight**frames
