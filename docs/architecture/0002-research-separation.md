# ADR 0002: Separate reference, optimized, and research implementations

Status: Accepted — 2026-07-12

## Decision

Gaussian algorithms with research claims expose explicit inputs, outputs, configuration, reference
implementations, optimized Metal implementations, benchmark hooks, and ablation switches. Novel
logic is not embedded in an application controller or generic renderer method.

GraphDECO code is not copied or linked. Brush and COLMAP are versioned external processes behind
adapters; provenance records their exact versions and arguments.

## Consequences

- CPU/GPU agreement and scientific ablations remain possible.
- A production viewer can ship even when a research hypothesis fails.
- External tool failures are structured job failures, not engine crashes.
