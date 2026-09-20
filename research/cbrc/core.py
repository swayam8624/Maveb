r"""Auditable reference implementation of Criticality-Bounded Revision Cones.

K[v, u] is the non-negative normalized influence gain from state block u -> v.
The unrepaired exterior is O = V \ C.

A result is conservative only when every K entry used for certification is a
valid upper bound over the declared revision domain. Empirical/predictive gains
must never be placed in K_cert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class QoI:
    """Linearized or bounded output operator and tolerance."""

    name: str
    R: np.ndarray
    epsilon: float


@dataclass(frozen=True)
class Certificate:
    cone: tuple[int, ...]
    exterior: tuple[int, ...]
    stable: bool
    reason: str
    bound_by_qoi: dict[str, float]
    passes: bool
    work: float
    full_work: float
    used_full_rebuild: bool
    transient_amplification: float | None
    susceptibility: float | None


def _as_matrix(x: np.ndarray | Sequence[Sequence[float]], *, name: str) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 2:
        raise ValueError(f"{name} must be a matrix")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must be finite")
    return a


def validate_transfer(K: np.ndarray) -> np.ndarray:
    K = _as_matrix(K, name="K")
    if K.shape[0] != K.shape[1]:
        raise ValueError("K must be square")
    if np.any(K < 0):
        raise ValueError("K must be componentwise non-negative")
    return K


def validate_vector(x: np.ndarray | Sequence[float], n: int, *, name: str) -> np.ndarray:
    a = np.asarray(x, dtype=float).reshape(-1)
    if a.shape != (n,):
        raise ValueError(f"{name} must have shape ({n},)")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must be finite")
    if np.any(a < 0):
        raise ValueError(f"{name} must be componentwise non-negative")
    return a


def predecessor_closure(
    seed: Iterable[int], exact_predecessors: Sequence[set[int]], n: int
) -> set[int]:
    """Return exact predecessor closure required to reproduce repaired state."""

    if len(exact_predecessors) != n:
        raise ValueError("exact_predecessors length must equal node count")
    closure = {int(v) for v in seed}
    if any(v < 0 or v >= n for v in closure):
        raise ValueError("seed contains invalid node")

    stack = list(closure)
    while stack:
        v = stack.pop()
        for u in exact_predecessors[v]:
            if u < 0 or u >= n:
                raise ValueError("exact predecessor contains invalid node")
            if u not in closure:
                closure.add(u)
                stack.append(u)
    return closure


def is_admissible(cone: set[int], exact_predecessors: Sequence[set[int]], n: int) -> bool:
    return predecessor_closure(cone, exact_predecessors, n) == set(cone)


def _spectral_radius(A: np.ndarray) -> float:
    if A.size == 0:
        return 0.0
    vals = np.linalg.eigvals(A)
    return float(np.max(np.abs(vals)))


def _resolvent_nonnegative(
    Koo: np.ndarray, *, tol: float = 1e-12
) -> tuple[np.ndarray | None, str]:
    """Return non-negative (I-Koo)^-1 when a stable response certificate exists."""

    m = Koo.shape[0]
    if m == 0:
        return np.zeros((0, 0)), "empty exterior"

    rho = _spectral_radius(Koo)
    if rho >= 1.0 - tol:
        return None, f"exterior spectral radius {rho:.6g} is not < 1"

    G = np.linalg.inv(np.eye(m) - Koo)
    if np.min(G) < -1e-9:
        return None, "resolvent is not componentwise non-negative"
    return np.maximum(G, 0.0), f"stable exterior spectral radius {rho:.6g}"


def _induced_one_norm(A: np.ndarray) -> float:
    if A.size == 0:
        return 0.0
    return float(np.max(np.sum(np.abs(A), axis=0)))


def _transient_amplification(Koo: np.ndarray, max_steps: int | None = None) -> float:
    """Finite diagnostic max_r ||Koo^r||_1; not itself the safety certificate."""

    m = Koo.shape[0]
    if m == 0:
        return 0.0
    steps = max_steps if max_steps is not None else max(1, 4 * m)
    power = np.eye(m)
    best = 1.0
    for _ in range(1, steps + 1):
        power = Koo @ power
        best = max(best, _induced_one_norm(power))
        if np.max(np.abs(power)) < 1e-14:
            break
    return float(best)


def certify_cone(
    *,
    K_cert: np.ndarray,
    source: np.ndarray | Sequence[float],
    true_change_bound: np.ndarray | Sequence[float],
    cone: Iterable[int],
    exact_predecessors: Sequence[set[int]],
    work: np.ndarray | Sequence[float],
    qois: Sequence[QoI],
    full_work_baseline: float | None = None,
) -> Certificate:
    """Certify a candidate repair cone against the full-after output contract."""

    K = validate_transfer(K_cert)
    n = K.shape[0]
    b = validate_vector(source, n, name="source")
    z = validate_vector(true_change_bound, n, name="true_change_bound")
    c = validate_vector(work, n, name="work")
    if full_work_baseline is None:
        full_work = float(c.sum())
    else:
        full_work = float(full_work_baseline)
        if not np.isfinite(full_work) or full_work < 0:
            raise ValueError("full_work_baseline must be finite and non-negative")

    C = set(int(v) for v in cone)
    if any(v < 0 or v >= n for v in C):
        raise ValueError("cone contains invalid node")

    if not is_admissible(C, exact_predecessors, n):
        return Certificate(
            cone=tuple(sorted(C)),
            exterior=tuple(sorted(set(range(n)) - C)),
            stable=False,
            reason="cone is not exact-predecessor consistent",
            bound_by_qoi={q.name: float("inf") for q in qois},
            passes=False,
            work=float(c[list(C)].sum()) if C else 0.0,
            full_work=full_work,
            used_full_rebuild=False,
            transient_amplification=None,
            susceptibility=None,
        )

    O = sorted(set(range(n)) - C)
    Cidx = sorted(C)
    local_work = float(c[Cidx].sum()) if Cidx else 0.0
    if not O:
        return Certificate(
            cone=tuple(Cidx),
            exterior=(),
            stable=True,
            reason="complete repair cone",
            bound_by_qoi={q.name: 0.0 for q in qois},
            passes=True,
            work=local_work,
            full_work=full_work,
            used_full_rebuild=False,
            transient_amplification=0.0,
            susceptibility=0.0,
        )

    Koo = K[np.ix_(O, O)]
    G, reason = _resolvent_nonnegative(Koo)
    if G is None:
        return Certificate(
            cone=tuple(Cidx),
            exterior=tuple(O),
            stable=False,
            reason=reason,
            bound_by_qoi={q.name: float("inf") for q in qois},
            passes=False,
            work=local_work,
            full_work=full_work,
            used_full_rebuild=False,
            transient_amplification=_transient_amplification(Koo),
            susceptibility=None,
        )

    frontier = b[O].copy()
    if Cidx:
        Koc = K[np.ix_(O, Cidx)]
        frontier += Koc @ z[Cidx]
    exterior_bound = G @ frontier

    bounds: dict[str, float] = {}
    passes = True
    for q in qois:
        if not (np.isfinite(q.epsilon) and q.epsilon >= 0):
            raise ValueError(f"QoI {q.name} epsilon must be finite and non-negative")
        R = _as_matrix(q.R, name=f"QoI[{q.name}].R")
        if R.shape[1] != n:
            raise ValueError(f"QoI {q.name} R must have {n} columns")

        # |R| is conservative for a componentwise non-negative state envelope.
        y = np.abs(R[:, O]) @ exterior_bound
        bound = float(np.max(y)) if y.size else 0.0
        bounds[q.name] = bound
        passes = passes and bound <= q.epsilon

    return Certificate(
        cone=tuple(Cidx),
        exterior=tuple(O),
        stable=True,
        reason=reason,
        bound_by_qoi=bounds,
        passes=passes,
        work=local_work,
        full_work=full_work,
        used_full_rebuild=False,
        transient_amplification=_transient_amplification(Koo),
        susceptibility=_induced_one_norm(G),
    )


def greedy_minimum_work_cone(
    *,
    K_cert: np.ndarray,
    source: np.ndarray | Sequence[float],
    true_change_bound: np.ndarray | Sequence[float],
    hard_closure: Iterable[int],
    exact_predecessors: Sequence[set[int]],
    work: np.ndarray | Sequence[float],
    qois: Sequence[QoI],
    full_work_baseline: float | None = None,
) -> Certificate:
    """Greedy certified expansion with a principled full-rebuild fallback.

    This returns a certified feasible cone, not a globally optimal cone.
    """

    K = validate_transfer(K_cert)
    n = K.shape[0]
    c = validate_vector(work, n, name="work")
    C = predecessor_closure(hard_closure, exact_predecessors, n)

    def score(cert: Certificate) -> float:
        if not cert.stable:
            return float("inf")
        return max(
            (
                cert.bound_by_qoi[q.name] / max(q.epsilon, 1e-15)
                for q in qois
            ),
            default=0.0,
        )

    current = certify_cone(
        K_cert=K,
        source=source,
        true_change_bound=true_change_bound,
        cone=C,
        exact_predecessors=exact_predecessors,
        work=c,
        qois=qois,
        full_work_baseline=full_work_baseline,
    )
    if current.passes and current.work < current.full_work:
        return current

    all_nodes = set(range(n))
    while C != all_nodes:
        base_violation = score(current)
        best = None

        for v in sorted(all_nodes - C):
            candidate_C = predecessor_closure(C | {v}, exact_predecessors, n)
            extra = candidate_C - C
            extra_work = float(c[list(extra)].sum())

            cert = certify_cone(
                K_cert=K,
                source=source,
                true_change_bound=true_change_bound,
                cone=candidate_C,
                exact_predecessors=exact_predecessors,
                work=c,
                qois=qois,
                full_work_baseline=full_work_baseline,
            )
            next_violation = score(cert)
            if np.isinf(base_violation) and np.isfinite(next_violation):
                utility = float("inf")
            elif np.isfinite(base_violation) and np.isfinite(next_violation):
                improvement = base_violation - next_violation
                utility = (
                    float("inf")
                    if extra_work == 0.0 and improvement > 0.0
                    else 0.0
                    if extra_work == 0.0
                    else improvement / extra_work
                )
            else:
                utility = float("-inf")
            key = (1 if cert.passes else 0, utility, -cert.work)
            if best is None or key > best[0]:
                best = (key, candidate_C, cert)

        if best is None:
            C = all_nodes
            break

        _, C, current = best
        if current.passes:
            if current.work < current.full_work:
                return current
            break

    complete = certify_cone(
        K_cert=K,
        source=source,
        true_change_bound=true_change_bound,
        cone=all_nodes,
        exact_predecessors=exact_predecessors,
        work=c,
        qois=qois,
        full_work_baseline=full_work_baseline,
    )
    if complete.work < complete.full_work:
        return complete
    return Certificate(
        cone=complete.cone,
        exterior=complete.exterior,
        stable=True,
        reason="full rebuild fallback",
        bound_by_qoi=complete.bound_by_qoi,
        passes=True,
        work=complete.full_work,
        full_work=complete.full_work,
        used_full_rebuild=True,
        transient_amplification=complete.transient_amplification,
        susceptibility=complete.susceptibility,
    )


def effectivity(certified_bound: float, measured_error: float, floor: float = 1e-15) -> float:
    if certified_bound < 0 or measured_error < 0:
        raise ValueError("bound and error must be non-negative")
    return float(certified_bound / max(measured_error, floor))
