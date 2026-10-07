# Editorial Reframe — 2026-10-07

## Trigger

Computer Graphics Forum returned manuscript 9292930 at pre-review. The editor stated that persistent 3D worlds are potentially in scope, but the technical computer-graphics contribution was difficult to identify and that the writing introduced too many concepts without sufficiently clear motivation or explanation.

## Revision objective

This revision does not change the reported experiments or invent a new result. It changes how the existing method is presented so that the graphics problem, algorithm, assumptions, and contribution boundary are explicit from the title onward.

## Changes made

- Retitled the manuscript to **Repair What Matters: Certified Local Recompute for Persistent 3D Reconstructions**.
- Rewrote the abstract around the concrete decision problem: full rebuild versus bounded local recomputation.
- Rewrote the introduction around a simple physical-edit example and explicitly separated **computational locality** from **output locality**.
- Defined a **revision cone** immediately as the state selected for recomputation instead of relying on the term before explanation.
- Reduced the method to a four-step algorithm: exact dependency closure, conservative exterior propagation, output-tolerance checking, and work-aware local/full selection.
- Made the source of dependencies explicit: ownership, identity, topology, publication, and temporal metadata already carried by the engine; no learned dependency discovery is used for correctness.
- Clarified that the current revision does not need to be globally executed before the planner can decide; full-after replay is an independent evaluation oracle.
- Defined the protected output, tolerance, calibrated work model, and kappa coefficients in plain language.
- Renamed the core method section to **Algorithm: Certified Local Recompute** and reduced jargon around revision criticality and fallback.
- Reframed related work around the missing cross-derived-state graphics decision rather than presenting the paper as a loose combination of old ideas.
- Rewrote system implementation to explain how dependencies are constructed in the actual C++/graphics pipeline.
- Simplified the evaluation questions and made fallback an explicit algorithmic outcome rather than an apparent failure.
- Rewrote the discussion around the method's operating region and the exact technical contribution.
- Rewrote the conclusion around the bounded claim and remaining open problems.
- Updated keywords and figure captions to use standard computer-graphics language.

## Claims intentionally unchanged

The numerical results, dataset counts, broad-campaign outcomes, residual-sensitive v4/v5/v6 evidence, work-ratio interpretation, certificate limitations, and runtime limitations are unchanged. The revision is a clarity and positioning pass, not a post-hoc alteration of evidence.

## Build synchronization

The synchronized PDF, DOCX, supplement, package, and checksum artifacts were regenerated successfully from this revised source by the manuscript workflow before merge.

## Final QA

The tightened 229-word abstract preserves the frozen headline evidence and the repository's manuscript QA terminology. The source and synchronized PDF/DOCX/supplement/package were rebuilt successfully after this final wording pass.

## Final terminology check

The final abstract uses the repository's expected graphics terminology (including AR maps and digital twins), remains below the 260-word QA ceiling, and was rebuilt into synchronized submission artifacts successfully.
