# Evidence Levels

AETHER requires all roadmap items and features to be backed by concrete evidence. Marketing claims and premature gate closures are not permitted.

Every feature in the roadmap must be marked with its current evidence level:

*   **E0** — designed (The feature is specified and documented, but no code exists)
*   **E1** — compiles (The feature is implemented in code and successfully compiles)
*   **E2** — fixture tested (The feature is covered by synthetic or mocked integration tests)
*   **E3** — real scene verified (The feature has been manually verified on a real-world object/scene)
*   **E4** — public reproducible benchmark (The feature has an automated, reproducible benchmark with raw results committed)

Compilation or file export alone never proves reconstruction. Reconstruction evidence must identify
the depth source, pose source, calibration, coordinate convention, volume configuration, input
hashes, geometry metrics, and whether the sequence is synthetic, recorded oracle, LiDAR, or
RGB-derived depth. A PLY file is evidence of serialization only until its source geometry passes the
corresponding accuracy gate.
