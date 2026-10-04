# MAVEB licensing map

MAVEB contains software, research writing, generated figures, derived scene visualizations, and third-party components. Those materials should not be treated as though they all have the same copyright or redistribution status.

## 1. Software

Unless a file or directory states otherwise, original MAVEB/AETHER software is licensed under the **Apache License 2.0**.

This includes original:

- C++ and Objective-C++ source;
- Swift application code;
- Python research and benchmark code;
- shell scripts;
- tests;
- build files;
- configuration files authored for MAVEB.

The full Apache-2.0 license is in [LICENSE](LICENSE).

SPDX identifier:

```text
Apache-2.0
```

Apache-2.0 is used for software because it supports broad academic and commercial reuse and includes an explicit patent grant.

## 2. Original research communication

Original MAVEB research text and project-authored research communication are licensed under the **Creative Commons Attribution 4.0 International License (CC BY 4.0)**, except where they incorporate or reproduce third-party material.

This scope includes original:

- research documentation;
- mathematical exposition;
- diagrams;
- tables;
- figure layouts and annotations;
- non-scene explanatory artwork;
- manuscript-support material.

License:

https://creativecommons.org/licenses/by/4.0/

Legal code:

https://creativecommons.org/licenses/by/4.0/legalcode

Suggested attribution:

```text
MAVEB / Criticality-Bounded Revision Cones, Swayam Singal, 2026.
Licensed under CC BY 4.0.
```

## 3. Scene-bearing figures, GIFs, and derived outputs

A scene-bearing visualization may include content derived from a public dataset or externally trained representation. The project does **not** use CC BY 4.0 to overwrite upstream rights.

The relevant files include material under:

```text
research/results/visualizations/
```

For these assets, reuse must satisfy both:

1. any rights held in MAVEB's original plotting, layout, annotation, or transformation; and
2. the applicable upstream dataset/model license, attribution, or research-use conditions.

The canonical source/provenance records are:

- `research/config/cbrc_public_real_sources.json`
- campaign `PUBLIC_SOURCE_PROVENANCE.json` artifacts;
- trained-3DGS `TRAINED_3DGS_SOURCE.json` artifacts;
- `research/results/CBRC_CANONICAL_EVIDENCE_2026-09-21.json`.

### Tanks and Temples

The Train and Truck scenes used by the public campaign are recorded as **CC BY 4.0** in the frozen source manifest. Preserve dataset attribution when those scenes appear in figures, videos, or supplementary material.

### Deep Blending

The Dr Johnson and Playroom scenes are recorded with an upstream-use note rather than a blanket repository license. They are used for research/evaluation with attribution preserved. Before manuscript submission or redistribution of scene imagery, verify and document the current upstream terms.

### Public trained 3DGS source

The pinned trained PLY is fetched from an external repository and is **not redistributed by MAVEB**. Its resolved source metadata, file hash, and any license value exposed by the source host are frozen in `TRAINED_3DGS_SOURCE.json` at campaign time.

Do not assume that the trained source PLY or derivatives are relicensed by this repository.

## 4. Third-party software and adapted source

Third-party components retain their original licenses.

Relevant notices include:

- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- `external/metal-cpp/LICENSE.txt`
- per-component license files where present.

## 5. Publication and ACM rights

Repository licensing and publication rights are separate questions.

For a SIGGRAPH, SIGGRAPH Asia, ACM TOG, or other ACM submission:

- identify all third-party images/data represented in the paper and video;
- retain evidence of the right to use them;
- complete the publisher's rights workflow as required;
- do not infer publication permission merely from public online availability.

## 6. No change to third-party rights

Nothing in this repository's Apache-2.0 or CC BY 4.0 declarations grants rights that the MAVEB authors do not own.
