"""Machine-readable evidence artifact for one CBRC revision."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class QoIResult:
    epsilon: float
    certified_bound: float
    measured_full_reference_error: float | None = None

    @property
    def certificate_violation(self) -> bool | None:
        if self.measured_full_reference_error is None:
            return None
        return self.measured_full_reference_error > self.certified_bound

    @property
    def tolerance_violation(self) -> bool | None:
        if self.measured_full_reference_error is None:
            return None
        return self.measured_full_reference_error > self.epsilon


@dataclass(frozen=True)
class RevisionCertificateArtifact:
    schema_version: int
    git_sha: str
    scene_id: str
    revision_id: str
    graph_version: str
    bound_version: str
    hard_closure_nodes: int
    repair_cone_nodes: int
    total_nodes: int
    fallback_full: bool
    stable: bool
    planner_work: float
    full_work: float
    qois: Mapping[str, QoIResult]
    work_ledger: Mapping[str, object]
    assumptions: tuple[str, ...] = ()

    def validate(self, *, require_oracle: bool = False) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported revision-certificate schema")
        if self.total_nodes <= 0:
            raise ValueError("total_nodes must be positive")
        if not 0 <= self.hard_closure_nodes <= self.repair_cone_nodes <= self.total_nodes:
            raise ValueError("invalid closure/cone cardinalities")
        if self.planner_work < 0 or self.full_work < 0:
            raise ValueError("work must be non-negative")
        if not self.qois:
            raise ValueError("at least one QoI is required")

        for name, qoi in self.qois.items():
            if qoi.epsilon < 0 or qoi.certified_bound < 0:
                raise ValueError(f"QoI {name} has negative tolerance/bound")
            if self.stable and qoi.certified_bound > qoi.epsilon:
                raise ValueError(f"stable certificate for {name} exceeds tolerance")
            if require_oracle and qoi.measured_full_reference_error is None:
                raise ValueError(f"QoI {name} is missing full-reference measurement")
            if qoi.certificate_violation:
                raise ValueError(
                    f"QoI {name} violates certificate: actual > certified bound"
                )

    def to_dict(self) -> dict:
        result = asdict(self)
        result["qois"] = {
            name: {
                **asdict(qoi),
                "certificate_violation": qoi.certificate_violation,
                "tolerance_violation": qoi.tolerance_violation,
            }
            for name, qoi in self.qois.items()
        }
        result["cone_fraction"] = self.repair_cone_nodes / self.total_nodes
        result["hard_closure_fraction"] = self.hard_closure_nodes / self.total_nodes
        result["work_ratio_full"] = (
            None if self.full_work == 0 else self.planner_work / self.full_work
        )
        return result

    def write(self, path: Path, *, require_oracle: bool = False) -> None:
        self.validate(require_oracle=require_oracle)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
