"""Frozen scalar cost model for CBRC planning.

LocalityLedger counters remain in native units. The planner may only combine
heterogeneous domains after applying an explicit, versioned conversion model,
for example milliseconds per native unit from a pre-frozen calibration set.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Any


@dataclass(frozen=True)
class DomainCost:
    unit: str
    cost_per_unit: float


@dataclass(frozen=True)
class WorkCostModel:
    version: str
    domains: Mapping[str, DomainCost]
    cost_unit: str = "ms"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "WorkCostModel":
        version = str(data.get("version", "")).strip()
        cost_unit = str(data.get("cost_unit", "ms")).strip()
        domains_raw = data.get("domains")
        if not version:
            raise ValueError("work cost model requires non-empty version")
        if not cost_unit:
            raise ValueError("work cost model requires non-empty cost_unit")
        if not isinstance(domains_raw, Mapping) or not domains_raw:
            raise ValueError("work cost model requires non-empty domains")

        domains: dict[str, DomainCost] = {}
        for name, item in domains_raw.items():
            if not isinstance(item, Mapping):
                raise ValueError(f"work cost domain {name} must be an object")
            unit = str(item.get("unit", "")).strip()
            coefficient = float(item.get("cost_per_unit"))
            if not unit:
                raise ValueError(f"work cost domain {name} requires unit")
            if not math.isfinite(coefficient) or coefficient < 0.0:
                raise ValueError(
                    f"work cost domain {name} coefficient must be finite and non-negative"
                )
            domains[str(name)] = DomainCost(unit=unit, cost_per_unit=coefficient)
        return cls(version=version, domains=domains, cost_unit=cost_unit)

    def estimate(
        self,
        ledger_domains: Mapping[str, Any],
        *,
        field: str,
    ) -> float:
        if field not in ("incremental", "full"):
            raise ValueError("field must be incremental or full")

        total = 0.0
        for name, counter in ledger_domains.items():
            if not isinstance(counter, Mapping):
                raise ValueError(f"ledger domain {name} must be an object")
            value = float(counter.get(field, 0.0))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"ledger domain {name}.{field} must be finite/non-negative")
            if value == 0.0:
                continue
            if name not in self.domains:
                raise ValueError(
                    f"non-zero ledger domain {name} has no frozen scalar cost coefficient"
                )
            expected = self.domains[name]
            unit = str(counter.get("unit", "")).strip()
            if unit != expected.unit:
                raise ValueError(
                    f"ledger domain {name} unit {unit!r} != model unit {expected.unit!r}"
                )
            total += value * expected.cost_per_unit

        if not math.isfinite(total):
            raise ValueError("work estimate overflow")
        return total
