# MAVEB manuscript knowledge transfer

Status: final implementation and evidence handoff for manuscript construction

Prepared: 2026-09-21

Primary paper title:

# Repair What Matters: Criticality-Bounded Revision Cones for Persistent Captured Worlds

System name: MAVEB

Method name: Criticality-Bounded Revision Cones (CBRC)

Primary target: ACM SIGGRAPH Technical Papers, with SIGGRAPH Asia / Eurographics / Computer Graphics Forum as structurally compatible alternatives depending on the final submission calendar and desired track.

This document is the manuscript handoff. It consolidates the scientific story, evidence, figures, exact repository paths, claims, limitations, provenance, licensing constraints, venue formatting, and reviewer-facing risks. The manuscript should use this document together with the canonical machine-readable evidence rather than reconstructing project history from individual commits.

# 1. One-sentence paper

Persistent captured worlds should not be globally rebuilt after every local physical change; MAVEB uses Criticality-Bounded Revision Cones to certify when a smaller cross-representation repair is safe for an explicit output tolerance and falls back to a full rebuild when it cannot prove locality.

# 2. One-paragraph paper kernel

Captured-world systems maintain heterogeneous state spanning observations, reconstructed geometry, textures, Gaussian primitives, GPU publication, and temporal history. A local physical change can therefore have a non-local computational effect. Existing local-update heuristics can reduce work but do not generally certify the error left outside the updated region, while full rebuilds preserve correctness at unnecessary cost when most state is irrelevant to the protected output. MAVEB introduces Criticality-Bounded Revision Cones, a fail-closed revision planner that combines exact dependency closure with conservative analytic finite-change bounds and quantity-of-interest tolerances. A candidate repair cone is accepted only when the unrepaired exterior is bounded below the declared tolerance and the calibrated regional work is lower than a full rebuild; otherwise MAVEB chooses FULL. The final public campaign contains 60 frozen revisions across four public RGB/SfM scenes, with 44 certified-local repairs, 16 automatic FULL fallbacks, zero observed certificate violations, and native/Python planner parity on all cases. A secondary trained-3DGS validation records 4 certified-local cases, 1 FULL fallback, and zero observed violations. The project reports work reduction rather than wall-clock speedup and preserves the near-full Gaussian discovery bottleneck as a measured limitation.

# 3. Paper identity

## Recommended title

Repair What Matters: Criticality-Bounded Revision Cones for Persistent Captured Worlds

Why this title is preferred:

1. "Repair What Matters" states the central intuition without sounding like a software feature name.
2. "Criticality-Bounded Revision Cones" names the method.
3. "Persistent Captured Worlds" defines the application scope.
4. It avoids claims of optimality, universal safety, or speedup.
5. MAVEB remains the system name in the abstract, implementation, repository, and video.

## Short running title

Repair What Matters

## Alternative titles retained only if the framing changes

1. MAVEB: Dependency-Certified Local Revision of Persistent Captured Worlds
2. Certified Local Repair for Persistent Captured Worlds
3. Criticality-Bounded Revision Cones for Persistent Captured Worlds
4. When Not to Rebuild the World: Certified Revision Cones for Persistent Captured Worlds

The primary title is preferred because it is more memorable than the purely descriptive alternatives while remaining technically accurate.

# 4. Core research question

Given a physical revision to a persistent captured world, can a system repair only a subset of the derived state while certifying that the unrepaired exterior cannot change a declared output beyond tolerance?

The essential contrast is:

- FULL rebuild: safe reference, potentially excessive work.
- heuristic local repair: potentially low work, no general output-error certificate.
- CBRC: local only when the exterior is conservatively certified; FULL otherwise.

# 5. Primary contribution

The proposed contribution is not graph traversal, Gaussian splatting, TSDF fusion, alpha compositing, temporal filtering, resolvents, or greedy search in isolation.

The contribution is the captured-world specialization and end-to-end systems contract:

1. A typed revision graph spans heterogeneous captured-world and runtime state.
2. Exact HARD dependencies and conservative ANALYTIC dependencies coexist.
3. EMPIRICAL dependencies may schedule work but never certify it.
4. Safety is defined at an explicit quantity of interest.
5. A local repair is accepted only when the unrepaired exterior is conservatively bounded.
6. Unsupported coupling fails closed and selects FULL.
7. Heterogeneous work is compared through a frozen versioned cost model.
8. The native decision is independently replayed against a full-reference oracle.
9. Each decision, bound, work result, provenance record, and failure can be retained as evidence.

# 6. Canonical mathematical story

The full derivation is in README.md and the CBRC theory/design files.

The manuscript should introduce the mathematics in this order.

## 6.1 Revision cone and exterior

Define world-state blocks V, the selected repair cone C, and exterior O = V minus C.

Explain that state blocks are representation and runtime units, not necessarily spatial voxels.

## 6.2 Exact closure

HARD predecessor closure ensures that a repaired node cannot omit exact state required to reproduce it.

This is structural correctness, not an approximation.

## 6.3 Analytic influence

Define a componentwise non-negative conservative influence matrix K.

Each ANALYTIC edge is an implementation-backed finite-change upper bound.

Empirical Jacobians or learned influence predictors do not enter the certificate.

## 6.4 Exterior response

For a certifiable exterior, use the path-sum / resolvent response to bound change remaining outside the cone.

The resolvent is classical. Do not claim the matrix identity as novel.

The paper contribution is the captured-world dependency specialization and use of that response in a fail-closed repair decision.

## 6.5 Quantity of interest

Map the exterior state envelope through an output-specific operator.

The paper should make the complete contract visually prominent:

independent measured full-reference error <= certified bound <= declared tolerance

## 6.6 Gaussian image bound

Explain the renderer-compatible effective alpha model, aggregate edited opacity mass, and the resulting protected-pixel color bound.

This is one of the most graphics-specific mathematical components and should receive a concrete visual.

Canonical source:

research/theory/alpha_locality_bound.md

Implementation:

research/cbrc/layer_bounds.py

tools/maveb-cbrc-gaussian-oracle/main.cpp

## 6.7 Temporal bound

Explain stable history reuse as a bounded blend.

When validation/disocclusion may change, the dependency becomes HARD and history is invalidated.

This is an important example of fail-closed design.

## 6.8 Work model

Do not add pixels, bytes, Gaussians, and TSDF blocks directly.

The public campaign uses a frozen calibrated heterogeneous cost model.

The manuscript may say "2.706x lower calibrated work" but not "2.706x speedup."

## 6.9 Search

The v1 search is greedy.

The paper must say "certified feasible cone" rather than "global minimum-work cone."

# 7. Exact evidence to use

The canonical machine-readable source is:

research/results/CBRC_CANONICAL_EVIDENCE_2026-09-21.json

Human-readable freeze:

research/results/CBRC_CANONICAL_EVIDENCE_2026-09-21.md

Claim ledger:

research/results/CBRC_CLAIM_LEDGER_2026-09-21.md

## 7.1 Public v2.1 campaign

Canonical workflow run: 35576709420

Canonical artifact ID: 10629865889

Execution test-merge SHA: ccc8413674933e5a2d58d2ee1a4fd949bd9806ea

Artifact ZIP SHA-256:

0a69bf097658024856ce92cad6581172d5de08ad73eebc0cf2be68f5110876fe

Campaign result:

- 60 frozen revision cases
- 4 public RGB/SfM scenes
- 44 certified-local selections
- 16 automatic FULL fallbacks
- 0 observed certificate violations
- 60/60 native/Python planner parity
- 56/60 source edits exceed the protected RGB tolerance before repair
- median calibrated heterogeneous work / FULL = 0.3695301075670818
- calibrated work reduction factor = 2.7061394444523503x
- maximum measured selected RGB residual = 0.0
- maximum selected certified bound = 2e-6
- sparse candidate discovery exact selection agreement = true
- sparse median inspected fraction = 0.01
- sparse minimum inspected fraction = 0.001

Interpretation:

The 2.706x result is lower calibrated heterogeneous work under a frozen isolated millisecond model. It is not a paired end-to-end wall-clock speedup.

## 7.2 Trained-3DGS validation

Canonical workflow run: 35576709338

Canonical artifact ID: 10628629024

Artifact ZIP SHA-256:

e55bf8899072ece49f776bba2d853ddb7bbfdede1f99e7ee8e57e58d22634d4d

Pinned PLY SHA-256:

f03e4979ac27345da1422d960d604b98db9541bdb3586d135d64bb4d9bde8eb3

Result:

- 5 revision cases
- 1 public trained-3DGS scene
- 4 certified-local selections
- 1 automatic FULL fallback
- 0 observed certificate violations
- median selected temporal/output work / FULL = 0.03494791666666667
- native work reduction factor = 28.614008941877792x
- median gaussiansInspected / FULL = 0.9999972000873573
- median gaussiansUpdated / FULL = 0.018153700271218206
- median GPU publication bytes / FULL = 0.018153700271218206
- median temporal pixels invalidated / FULL = 0.03494791666666667

Interpretation:

The 28.614x result is lower native temporal/output work, not wall-clock speedup.

Persistent ownership is deterministic spatial ownership, not semantic segmentation.

# 8. Main paper narrative

A SIGGRAPH-style paper should make the problem readable before introducing the graph formalism.

Recommended narrative:

## 8.1 Teaser

Show a local revision that is certified, repaired regionally, and matches FULL.

Show a second high-coupling case that expands or falls back to FULL.

The visual sentence is:

local when proven safe, FULL when not

Recommended asset:

research/results/visualizations/public/F0_hero.png

## 8.2 Introduction

Paragraph 1:

Persistent captured worlds are long-lived and change after capture.

Paragraph 2:

Modern systems contain heterogeneous derived state. A local physical edit can cause non-local computational dependencies.

Paragraph 3:

Full rebuilds are safe but wasteful. Local heuristics save work but do not establish the output error left outside the update.

Paragraph 4:

Introduce CBRC as a fail-closed decision layer.

Paragraph 5:

Summarize evidence and limitations without overstating speed.

Contribution list should be short, approximately four items:

1. A typed fail-closed revision formulation for heterogeneous captured worlds.
2. Conservative output-specific certification including Gaussian and temporal bounds.
3. A work-aware native planner with FULL fallback and independent full-reference falsification.
4. Frozen public and trained-representation evidence with explicit crossover, sparse-discovery, and failure-regime reporting.

## 8.3 Related work

Use four groups rather than a chronology dump:

1. Persistent reconstruction and incremental map maintenance.
2. Continual and dynamic Gaussian scene representations.
3. Local editing, change detection, and persistent identity.
4. Incremental computation, dependency propagation, and certified/error-bounded selective work.

End related work with the exact gap:

prior work contains local updates, persistent state, dynamic representations, dependency reasoning, and error analysis, but MAVEB targets one cross-derived-state fail-closed revision contract tied to an explicit output tolerance and full-reference falsification.

## 8.4 Problem formulation

Introduce C, O, HARD, ANALYTIC, EMPIRICAL, quantity of interest, tolerance, and work.

State assumptions before the theorem-like derivation.

## 8.5 Method

Recommended subsections:

1. Typed revision graph
2. Exact predecessor closure
3. Exterior influence certificate
4. Gaussian display-space bound
5. Temporal bound and hard invalidation
6. Work-aware cone selection
7. FULL fallback and transaction publication
8. Native certificate and oracle replay

## 8.6 Implementation

Keep engineering details that support scientific claims:

- C++23 sparse native planner
- dense Python reference
- immutable revision sidecars
- indexed Gaussian update path
- atomic GPU publication semantics
- temporal handling
- deterministic certificate JSON
- work calibration
- independent oracle

Move ordinary software architecture detail to supplement.

## 8.7 Evaluation

Evaluation should answer explicit questions:

RQ1. Does the certificate survive independent full-reference replay?

RQ2. When does CBRC choose a local cone versus FULL?

RQ3. How much calibrated work is selected relative to FULL?

RQ4. Which layers remain local and which remain global bottlenecks?

RQ5. How do fixed-radius, exact, fraction, empirical, and ablated planners behave?

RQ6. Does the contract transfer from SfM-seeded fields to a trained 3DGS representation?

RQ7. Can exact sparse discovery remove the current full-scan candidate bottleneck?

## 8.8 Discussion

Discuss:

- zero selected residual and source-effect sanity check
- conservative bounds
- neutral real-matrix ablations
- empirical scheduler boundary
- near-full Gaussian inspection
- trained-representation scope
- greedy search
- unsupported analytic cycles
- external validity

## 8.9 Conclusion

Return to the decision principle:

A persistent-world system should not rebuild everything by default, but it should also not assume locality. It should repair locally only when it can justify the unrepaired exterior for the output that matters.

# 9. Figure plan

Canonical committed media directory:

research/results/visualizations/

Recommended main-paper allocation:

## Teaser

F0 hero

Path:

research/results/visualizations/public/F0_hero.png

Role:

One local certified case plus one fallback case. This should be the first visual claim.

## Figure 1: system overview

Path:

research/results/visualizations/public/F0_system_overview.svg

Role:

revision -> closure/bounds -> local or FULL -> oracle -> evidence

## Figure 2: certificate validity

Path:

research/results/visualizations/paper/F1_actual_vs_bound.svg

Possible paired inset:

research/results/visualizations/paper/F5_effectivity.svg

Role:

measured error versus bound and certificate tightness where defined

## Figure 3: work scaling

Paths:

research/results/visualizations/paper/F2_work_vs_changed_fraction.svg

research/results/visualizations/paper/F6_layer_work.svg

Role:

selected calibrated work and layer decomposition

## Figure 4: criticality and fallback

Paths:

research/results/visualizations/paper/F3_coupling_cone.svg

research/results/visualizations/paper/F4_fallback_crossover.svg

research/results/visualizations/paper/F8_adversarial_fallback.svg

Role:

show that CBRC does not force incremental execution

## Figure 5: spatial certificate evidence

Path:

research/results/visualizations/paper/F7_cone_support_residual.svg

Role:

connect graph/certificate language to actual image-space support and residual

## Figure 6: frozen-case coverage

Path:

research/results/visualizations/public/F10_case_mosaic.png

Role:

show breadth of cases rather than one cherry-picked example

If page pressure is high, move the full mosaic to the supplement and keep a smaller selection in the paper.

## Figure 7: sparse discovery

Path:

research/results/visualizations/sparse/F11_sparse_discovery.svg

Role:

show the separately validated path toward removing the full-scan bottleneck

## Figure 8: representation transfer

Path:

research/results/visualizations/representation/F12_representation_comparison.svg

Role:

show that the safety contract is also exercised on a pinned trained 3DGS representation

## Evidence dashboard

Path:

research/results/visualizations/public/F9_evidence_dashboard.png

Use:

supplement, paper overview, or presentation. Avoid duplicating numerical content already shown in individual plots if page space is tight.

# 10. Animated media

Public teaser:

research/results/visualizations/public/MAVEB_teaser.gif

Public supplementary cases:

research/results/visualizations/public/MAVEB_supplementary_cases.gif

Trained-3DGS teaser:

research/results/visualizations/trained-3dgs/MAVEB_teaser.gif

Trained-3DGS supplementary cases:

research/results/visualizations/trained-3dgs/MAVEB_supplementary_cases.gif

Canonical storyboard:

research/visualization/SIGGRAPH_VISUAL_STORYBOARD.md

Visual generator:

research/visualization/cbrc_siggraph_visuals.py

Cross-representation generator:

research/visualization/cbrc_representation_comparison.py

Style configuration:

research/visualization/style.json

For SIGGRAPH review, generate an anonymized video package rather than linking reviewers to the identifiable public repository.

# 11. Tables to construct in the manuscript

## Table 1: method comparison

Rows:

- FULL
- EXACT
- fixed radius 0 to 3
- changed-fraction heuristic
- held-out empirical scheduler
- CBRC

Columns should separate:

- certificate eligible
- automatic FULL fallback
- pass rate
- work ratio
- decision rule

Do not create one number that hides safety failures.

## Table 2: public campaign summary

Columns:

- scene
- cases
- local
- FULL
- violations
- median calibrated work / FULL
- source-effect cases

Use machine-readable campaign output rather than manual transcription.

## Table 3: layer work

Columns:

- Gaussian inspection
- Gaussian update
- GPU publication bytes
- temporal invalidation
- any additional registered native domains

Keep units explicit.

## Table 4: ablation summary

Separate:

- real-matrix ablations
- synthetic mechanism-isolation suite

Do not describe a neutral real-matrix ablation as evidence of mechanism necessity.

## Table 5: representation check

Compare public SfM-seeded path and trained-3DGS path only on compatible safety-contract properties.

Do not imply direct performance ranking when source representations and work units differ.

# 12. Baselines

Repository baseline ledger:

research/literature/baselines.md

Current implemented baseline suite:

research/experiments/cbrc_baseline_suite.py

Required method-level baselines:

- FULL
- EXACT
- RADIUS_0
- RADIUS_1
- RADIUS_2
- RADIUS_3
- FRACTION
- EMPIRICAL
- CBRC

Ablation suite:

research/experiments/cbrc_ablation_stress_suite.py

Held-out empirical scheduler:

research/experiments/cbrc_empirical_heldout.py

Reviewer-facing rule:

The paper should compare against the strongest fair baselines available under the same revision/output contract. If a related continual-Gaussian system cannot be reproduced under the same persistent-world edit and certificate task, explain the contract mismatch rather than inventing a numeric comparison.

# 13. Literature map

Internal literature sources:

research/literature/papers.csv

research/literature/papers.json

research/literature/novelty_matrix.md

research/literature/baselines.md

research/literature/open_questions.md

The novelty matrix already records killed generic claims, including:

- generic local continual Gaussian update
- generic bounded-compute Gaussian scheduling
- primitive-space Gaussian change detection
- persistent Gaussian/object identity
- fixed mesh plus Gaussian hybrid
- mobile/Metal Gaussian rendering

These can appear as related mechanisms, not headline novelty.

Closest collision classes that must be refreshed immediately before submission:

1. continual/local Gaussian mapping and editing
2. hybrid TSDF plus Gaussian change-aware mapping
3. object-centric lifelong Gaussian maintenance
4. semantic object-submodel update methods
5. persistent-density Gaussian representations
6. incremental Gaussian streaming/delivery
7. incremental scene-graph/render-cache dependency systems
8. self-adjusting and incremental computation
9. certified or goal-oriented error control for selective recomputation

A last literature refresh is mandatory because this area is moving quickly.

# 13A. Highest-priority collision papers already in the project corpus

These entries deserve explicit treatment in the related-work and novelty discussion because the internal literature matrix marks them as high or very high collision classes:

- CL-Splats: Continual Learning of Gaussian Splatting with Local Optimization
- GaussianUpdate: Continual 3D Gaussian Splatting Update for Changing Environments
- Gaussian Mapping for Evolving Scenes (GaME)
- From Pixels to Primitives: Scene Change Detection in 3D Gaussian Splatting
- Consistent Instance Field for Dynamic Scene Understanding
- EliGSiR: Continual RGB-D Mapping with Gaussian Splatting under Bounded Compute
- SplaTAM
- Gaussian Splatting SLAM / MonoGS
- GaussianEditor variants
- SC-GS
- EditSplat
- InterGSEdit
- SuGaR
- hierarchical 3D Gaussians

The internal corpus also contains preprints and provisional metadata. Before any item is placed into the final bibliography, verify the title, authors, venue status, year, DOI/arXiv identifier, and publication state from an authoritative source. Do not cite placeholder metadata such as "authors per paper" or a generic venue landing page.

# 14. Literature anchors already suitable for the paper

Use the project literature database for exact BibTeX, but the conceptual anchors include:

- Curless and Levoy, volumetric integration
- Surfels
- KinectFusion
- ElasticFusion
- BundleFusion
- NeRF
- iMAP
- NICE-SLAM
- 3D Gaussian Splatting
- Dynamic 3D Gaussians
- 4D Gaussian Splatting

The manuscript should add the closest 2025-2027 continual Gaussian / change-aware / incremental mapping work from the final literature refresh.

# 15. Reviewer attack checklist

The manuscript should answer these before submission.

## Attack 1: "This is just a dependency graph"

Answer:

No. Generic dependency propagation is not the novelty claim. The method distinguishes exact and conservative finite-change edges, computes an output-specific residual certificate, compares heterogeneous repair work with FULL, fails closed, and independently falsifies the emitted certificate.

## Attack 2: "This is just local Gaussian updating"

Answer:

The paper claim is cross-derived-state revision and certification. Gaussian locality is one analytic mechanism inside the system.

## Attack 3: "Zero residual means the edits are trivial"

Answer:

56/60 public source edits exceed the protected RGB tolerance before repair. Report this beside selected residual.

## Attack 4: "2.706x is not speedup"

Answer:

Correct. The paper must call it calibrated work reduction. A wall-clock speedup claim is intentionally absent.

## Attack 5: "You still inspect every Gaussian"

Answer:

Yes in the frozen end-to-end paths. Report this explicitly. The separate exact sparse-discovery sweep reaches a median 1 percent inspected fraction through the tested scale, but this optimization is not credited to the frozen end-to-end work result.

## Attack 6: "The real ablations do not separate"

Answer:

Report neutral real-matrix ablations honestly. The mechanism-isolation suite shows deterministic stress cases and is labeled synthetic.

## Attack 7: "The empirical baseline is also safe here"

Answer:

Its zero unsafe-false-local rate on this frozen matrix does not turn an empirical predictor into a certificate, particularly when candidate residuals are zero.

## Attack 8: "This is not globally optimal"

Answer:

Correct. V1 uses greedy certified feasible-cone search. Do not claim global optimality.

## Attack 9: "The method only works on seeded SfM Gaussians"

Answer:

The primary public path is SfM-seeded, and a secondary pinned trained-3DGS representation check exercises the same certificate/oracle contract.

## Attack 10: "Where is state-of-the-art superiority?"

Answer:

The strongest claim is a new fail-closed revision contract rather than universal speed dominance. For a SIGGRAPH Journal-level submission, the manuscript should still maximize fair comparisons and explain incompatible task contracts precisely.

# 16. Highest-value optional additions before submission

The current evidence is sufficient to begin the manuscript.

The following are optional strengthening work, not requirements for the existing claims.

## A. Paired end-to-end local versus FULL timing

Value:

Would permit a direct latency/speedup claim.

Current paper can proceed without it by keeping the calibrated-work wording.

## B. Integrate sparse discovery into the complete measured campaign

Value:

Would remove the most obvious systems bottleneck from the frozen end-to-end path.

Current paper must not credit this improvement before integration and rerun.

## C. More trained-3DGS scenes

Value:

Would strengthen representation generality.

Current five-case trained check should be described as secondary validation, not a broad benchmark.

## D. Closest reproducible continual-Gaussian baseline

Value:

Could strengthen a Journal-track state-of-the-art comparison if task contracts can be aligned fairly.

Do not force a mismatched comparison.

# 17. Venue strategy

## SIGGRAPH Technical Papers

Current ACM SIGGRAPH author guidance uses the acmtog style for Technical Papers and requires anonymous review formatting.

For LaTeX Technical Papers, the current author instructions specify:

<pre>
\documentclass[acmtog,anonymous,review]{acmart}
\acmSubmissionID{paperID}
\citestyle{acmauthoryear}
</pre>

Official author instructions:

https://www.siggraph.org/preparing-your-content/author-instructions/

SIGGRAPH 2026 used an integrated Journal and Conference Technical Papers model:

- Journal track: comprehensive, extensively validated work, no hard page maximum.
- Conference path in dual-track submission: maximum 7 pages excluding references, with up to two figures-only pages under the 2026 rules.
- Both use the same technical review process.
- Review is double blind.

2026 Technical Papers page:

https://s2026.siggraph.org/program/technical-papers/

Because SIGGRAPH 2027 rules may change, recheck the 2027 call when it is published before freezing manuscript length or supplemental format.

Recommended current planning choice:

Write the full evidence-complete version first at Journal-paper depth. Maintain a 7-page compression plan so a dual-track/conference-length version can be produced if the 2027 rules retain the 2026 model.

## SIGGRAPH Asia

The method and acmtog Technical Papers structure are directly compatible with SIGGRAPH Asia. Recheck the live year-specific call for page, video, and anonymity rules.

## Eurographics 2027

Eurographics 2027 Full Papers use double-blind review and the CGF submission style. The current author instructions recommend technical full papers around 10 pages excluding references, though CGF does not impose a strict universal maximum.

Current Eurographics 2027 Full Papers deadline information at the time of this KT:

- abstract deadline: 2026-09-25 23:59 UTC
- paper deadline: 2026-10-01 23:59 UTC

Official current page:

https://srmv2.eg.org/COMFy/Conference/EG_2027

This deadline is extremely close to the evidence freeze, so it is a calendar option rather than a reason to compress or weaken the paper.

## Computer Graphics Forum and related Eurographics special issues

CGF is structurally compatible with a longer systems/method paper. Current Eurographics guidance recommends technical full papers around 10 pages excluding references and encourages supplementary material.

# 18. SIGGRAPH submission hygiene

## Double-blind review

The public repository identifies its owner.

Do not place the public MAVEB GitHub URL in an anonymous SIGGRAPH submission.

Prepare an anonymized supplemental package or anonymized repository snapshot if code/data are required for review.

Strip:

- author names
- affiliations
- Git metadata that identifies authors
- account-specific URLs
- acknowledgments
- identifying filenames or comments where material

Review the year-specific anonymity policy immediately before submission.

## Public dissemination

Current SIGGRAPH policy permits preprints under conditions but restricts promotion and identifying submission information during the review period.

Do not state publicly that the work is "under review at SIGGRAPH."

Do not publish the submission ID.

Use the live conference anonymity policy rather than relying on this KT for exact future rules.

## Third-party material

ACM requires authors to identify third-party material and demonstrate permission or appropriate licensing.

The paper/video rights checklist must include:

- Tanks and Temples scene use and attribution
- Deep Blending scene use and current upstream terms
- trained-3DGS source attribution and terms
- any external icons, fonts, or media if later added

Repository licensing map:

LICENSES.md

Third-party notices:

THIRD_PARTY_NOTICES.md

# 19. Supplemental package plan

Recommended review supplement:

1. anonymized supplementary video
2. anonymized PDF appendix
3. machine-readable campaign summary
4. baseline/ablation tables
5. representative oracle evidence
6. anonymized code snapshot if allowed/useful
7. reproduction README

Do not require reviewers to inspect the public repository to understand the core claim.

The main paper must be self-contained.

# 20. Video plan

Canonical storyboard:

research/visualization/SIGGRAPH_VISUAL_STORYBOARD.md

Recommended paper video length:

2 to 4 minutes

Story:

1. persistent world changes
2. FULL versus heuristic locality
3. CBRC revision graph
4. HARD closure plus analytic bound
5. local certified example
6. full-reference residual
7. 60-case campaign
8. work decomposition
9. fallback case
10. trained-3DGS validation
11. limitation: discovery
12. closing principle

Teaser:

approximately 18 seconds

Existing inline GIFs can seed the video edit, but the final submission should use high-quality video output rather than a GIF container when the venue accepts it.

# 21. Paper writing order

Recommended drafting order:

1. Freeze title and contribution list.
2. Build LaTeX skeleton and figure slots.
3. Write Method from the current implementation.
4. Write Evaluation from canonical evidence.
5. Write Limitations and Discussion.
6. Refresh Related Work.
7. Write Introduction.
8. Write Abstract last.
9. Compress for the target track only after the full story works.
10. Perform claim audit against the claim ledger.
11. Perform rights and anonymity audit.
12. Generate final supplementary package.

# 22. Section-level evidence map

## Abstract

Use only canonical headline numbers.

Source:

research/results/CBRC_CANONICAL_EVIDENCE_2026-09-21.json

## Introduction

Problem and scope:

research/state/PROBLEM_LOCK.md

research/design/criticality_bounded_revision_cones.md

Current completion boundary:

research/design/CBRC_IMPLEMENTATION_STATUS.md

## Related work

research/literature/

research/mining/

## Method

research/cbrc/

research/theory/

engine/revision/

tools/maveb-cbrc-revision/

## Implementation

engine/

tools/

benchmarks/scripts/

## Evaluation protocol

research/config/

research/schema/

research/results/CBRC_EXPERIMENT_RUNBOOK.md

## Evaluation results

research/results/CBRC_CANONICAL_EVIDENCE_2026-09-21.json

research/results/CBRC_CLAIM_LEDGER_2026-09-21.md

research/results/visualizations/

## Limitations

research/design/CBRC_LIMITATIONS.md

## Negative results and history

research/negative_results/

research/LOG.md

research/hypotheses/

# 23. Canonical implementation paths

Reference certifier:

research/cbrc/core.py

Edge semantics:

research/cbrc/edges.py

Layer bounds:

research/cbrc/layer_bounds.py

Work model:

research/cbrc/work.py

Artifact helpers:

research/cbrc/artifact.py

Native revision tool:

tools/maveb-cbrc-revision/

Independent Gaussian oracle:

tools/maveb-cbrc-gaussian-oracle/

Work microbenchmark:

tools/maveb-cbrc-work-bench/

Trained-3DGS seeding:

tools/maveb-seed-trained-3dgs-world/

Public campaign:

run_public_real_campaign_v2.sh

Trained campaign:

run_trained_3dgs_campaign.sh

Complete paper-grade run:

run_paper_grade_research.sh

# 24. Canonical experiment and analysis paths

Campaign runner:

benchmarks/scripts/cbrc_campaign.py

Replay:

benchmarks/scripts/cbrc_replay.py

Strict evaluator:

benchmarks/scripts/cbrc_evaluate.py

Evidence bundle:

benchmarks/scripts/cbrc_evidence_bundle.py

Work calibration:

benchmarks/scripts/cbrc_calibrate_work.py

Public-data fetch:

benchmarks/scripts/cbrc_fetch_public_dataset.py

Trained-3DGS fetch:

benchmarks/scripts/cbrc_fetch_trained_3dgs.py

Public-v2 preparation:

benchmarks/scripts/cbrc_prepare_campaign_v2.py

Sparse sweep:

benchmarks/scripts/cbrc_sparse_discovery_sweep.py

Paper artifact generation:

research/analysis/cbrc_paper_artifacts.py

Paper readiness:

research/analysis/cbrc_paper_readiness.py

Campaign report:

research/analysis/cbrc_real_campaign_report.py

# 25. Tests that support manuscript trust

Core tests:

research/tests/test_cbrc_core.py

Edge semantics:

research/tests/test_cbrc_edges.py

Layer bounds:

research/tests/test_cbrc_layer_bounds.py

Work accounting:

research/tests/test_cbrc_work.py

Schemas:

research/tests/test_cbrc_schemas.py

Baseline suite:

research/tests/test_cbrc_baseline_suite.py

Mechanism stress:

research/tests/test_cbrc_ablation_stress_suite.py

Held-out empirical baseline:

research/tests/test_cbrc_empirical_heldout.py

Paper figures:

research/tests/test_cbrc_paper_artifacts.py

Readiness:

research/tests/test_cbrc_paper_readiness.py

SIGGRAPH visual generation:

research/tests/test_cbrc_siggraph_visuals.py

# 26. Claim ledger for manuscript authors

Safe:

"Across the frozen evaluated revisions, measured QoI error did not exceed the emitted certificate."

Safe:

"CBRC selected a certified local repair in 44 of 60 public cases and FULL in 16 of 60."

Safe:

"The public frozen cost model reports 2.706x lower calibrated work at the median."

Safe:

"The trained-3DGS validation reports 28.614x lower native temporal/output work at the median under its work definition."

Unsafe:

"CBRC is always safe."

Unsafe:

"CBRC achieves 2.706x speedup."

Unsafe:

"CBRC achieves 28.614x speedup."

Unsafe:

"CBRC finds the globally minimum-work repair."

Unsafe:

"All real-world ablations prove every mechanism is necessary."

Unsafe:

"The empirical scheduler is a certificate."

Unsafe:

"The trained representation uses semantic object segmentation."

# 27. Historical documents that are not the final result

Some research-state files were intentionally frozen earlier in the process and contain pre-evidence status flags such as PAPER_READY = false.

Do not treat those historical flags as current project status.

Current authoritative completion sources are:

README.md

research/design/CBRC_IMPLEMENTATION_STATUS.md

research/results/CBRC_CANONICAL_EVIDENCE_2026-09-21.json

research/results/CBRC_CLAIM_LEDGER_2026-09-21.md

This KT

# 28. Manuscript completion checklist

Before submission:

- title locked
- target track locked
- year-specific SIGGRAPH rules rechecked
- literature refreshed through submission date
- closest-collision table updated
- all figure numbers frozen
- all values programmatically sourced
- no stale 0.349 work ratio remains
- work reduction never called speedup
- 56/60 source-effect sanity check included
- discovery limitation included
- trained-3DGS scope described correctly
- real and synthetic ablations separated
- FULL fallback cases retained
- code/data supplement anonymized
- third-party rights documented
- references verified
- PDF anonymization checked
- metadata anonymization checked
- supplementary video anonymized
- claim ledger audited line by line
- final PDF inspected at 100 percent zoom
- all vector figures render correctly
- all fonts embedded
- no figure contains unsupported transparency for an alternative Eurographics submission

# 29. Final handoff

The engineering and evidence-construction phase is complete for CBRC v1.

The manuscript should now be built around one sentence:

Repair locally only when the unrepaired world can be proven irrelevant to the declared output; otherwise rebuild.

No new result should enter the paper unless it receives the same provenance, freeze, and claim-audit treatment as the existing canonical evidence.
