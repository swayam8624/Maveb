"""Typed dependency registry for CBRC certification.

EMPIRICAL dependencies are useful for ordering, but without an analytic upper
bound they are conservatively promoted to HARD propagation. Cone admissibility
uses all declared dependencies, restricted at runtime to predecessors whose
true-change bound is nonzero.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable

import numpy as np


class EdgeClass(str, Enum):
    HARD = "hard"
    ANALYTIC = "analytic"
    EMPIRICAL = "empirical"


@dataclass(frozen=True)
class RevisionEdge:
    src: int
    dst: int
    edge_class: EdgeClass
    gain: float | None = None
    bound_id: str | None = None


def validate_edges(node_count: int, edges: Iterable[RevisionEdge]) -> list[RevisionEdge]:
    result = list(edges)
    for edge in result:
        if not (0 <= edge.src < node_count and 0 <= edge.dst < node_count):
            raise ValueError("edge endpoint out of range")

        if edge.edge_class is EdgeClass.ANALYTIC:
            if edge.gain is None or not math.isfinite(edge.gain) or edge.gain < 0:
                raise ValueError("analytic edge requires finite non-negative gain")
            if not edge.bound_id:
                raise ValueError("analytic edge requires bound_id provenance")
        elif edge.edge_class is EdgeClass.HARD:
            if edge.gain is not None:
                raise ValueError("hard edge must not carry an approximate gain")
        elif edge.edge_class is EdgeClass.EMPIRICAL:
            if edge.gain is not None and (not math.isfinite(edge.gain) or edge.gain < 0):
                raise ValueError("empirical estimate must be finite and non-negative")
        else:
            raise ValueError("unknown edge class")
    return result


def certificate_transfer(node_count: int, edges: Iterable[RevisionEdge]) -> np.ndarray:
    """Construct K_cert from ANALYTIC edges only."""
    edges = validate_edges(node_count, edges)
    K = np.zeros((node_count, node_count), dtype=float)
    for edge in edges:
        if edge.edge_class is EdgeClass.ANALYTIC:
            K[edge.dst, edge.src] += float(edge.gain)
    return K


def exact_predecessors(
    node_count: int, edges: Iterable[RevisionEdge]
) -> list[set[int]]:
    """Return fail-closed predecessors.

    HARD dependencies are exact by definition. EMPIRICAL-only dependencies are
    also exact for certification because no conservative soft bound is known.
    """
    edges = validate_edges(node_count, edges)
    pred = [set() for _ in range(node_count)]
    for edge in edges:
        if edge.edge_class in (EdgeClass.HARD, EdgeClass.EMPIRICAL):
            pred[edge.dst].add(edge.src)
    return pred


def dependency_predecessors(
    node_count: int, edges: Iterable[RevisionEdge]
) -> list[set[int]]:
    """Return every declared predecessor for repair-cone admissibility."""
    edges = validate_edges(node_count, edges)
    pred = [set() for _ in range(node_count)]
    for edge in edges:
        pred[edge.dst].add(edge.src)
    return pred


def fail_closed_successors(
    node_count: int, edges: Iterable[RevisionEdge]
) -> list[set[int]]:
    """Return forward edges that must propagate exact repair."""
    edges = validate_edges(node_count, edges)
    succ = [set() for _ in range(node_count)]
    for edge in edges:
        if edge.edge_class in (EdgeClass.HARD, EdgeClass.EMPIRICAL):
            succ[edge.src].add(edge.dst)
    return succ


def hard_forward_closure(
    node_count: int, edges: Iterable[RevisionEdge], sources: Iterable[int]
) -> set[int]:
    """Exact forward closure of physical sources through fail-closed edges."""
    succ = fail_closed_successors(node_count, edges)
    closure = {int(v) for v in sources}
    if any(v < 0 or v >= node_count for v in closure):
        raise ValueError("source contains invalid node")
    stack = list(closure)
    while stack:
        u = stack.pop()
        for v in succ[u]:
            if v not in closure:
                closure.add(v)
                stack.append(v)
    return closure


def required_repair_closure(
    node_count: int,
    edges: Iterable[RevisionEdge],
    physical_sources: Iterable[int],
    true_change_bounds: Iterable[float],
) -> set[int]:
    """Return the fail-closed repair seed for one revision.

    This handles the soft->hard boundary that a pure physical-source hard
    closure misses. If an active state can change and feeds a HARD/EMPIRICAL
    successor that can also change, that exact successor must be repaired.
    Active predecessor closure then pulls in every changed dependency required
    to compute those repaired states correctly.

    A target whose true-change bound is exactly zero is not forced into repair:
    before and after are identical for that state.
    """
    edge_list = validate_edges(node_count, edges)
    bounds = np.asarray(list(true_change_bounds), dtype=float).reshape(-1)
    if bounds.shape != (node_count,):
        raise ValueError(f"true_change_bounds must have shape ({node_count},)")
    if not np.all(np.isfinite(bounds)) or np.any(bounds < 0.0):
        raise ValueError("true_change_bounds must be finite and non-negative")
    active = bounds > 0.0

    required = hard_forward_closure(node_count, edge_list, physical_sources)

    predecessors = dependency_predecessors(node_count, edge_list)
    for edge in edge_list:
        if (
            edge.edge_class in (EdgeClass.HARD, EdgeClass.EMPIRICAL)
            and active[edge.src]
            and active[edge.dst]
        ):
            required.add(edge.dst)

    stack = list(required)
    while stack:
        v = stack.pop()
        for u in predecessors[v]:
            if active[u] and u not in required:
                required.add(u)
                stack.append(u)
    return required


def empirical_priority(
    node_count: int, edges: Iterable[RevisionEdge]
) -> np.ndarray:
    """Optional scheduling score; this function never changes certification."""
    edges = validate_edges(node_count, edges)
    P = np.zeros((node_count, node_count), dtype=float)
    for edge in edges:
        if edge.edge_class is EdgeClass.EMPIRICAL and edge.gain is not None:
            P[edge.dst, edge.src] += float(edge.gain)
    return P
