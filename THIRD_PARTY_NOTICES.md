# Third-party notices

## PoissonRecon Marching Cubes topology table

`engine/reconstruction/src/ReferenceMarchingCubes.cpp` adapts the classic topology table from
PoissonRecon's `MarchingCubes.cpp`, as distributed in the repository's pinned COLMAP source.

```text
Copyright (c) 2006, Michael Kazhdan and Matthew Bolitho
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted
provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions
   and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of
   conditions and the following disclaimer in the documentation and/or other materials provided
   with the distribution.
3. Neither the name of the Johns Hopkins University nor the names of its contributors may be used
   to endorse or promote products derived from this software without specific prior written
   permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```


## Public research datasets used in MAVEB evidence

### Tanks and Temples

MAVEB's frozen public campaign uses the Train and Truck scenes from the public Tanks and Temples material distributed in the pinned GraphDECO input bundle.

The project source manifest records these scenes as CC BY 4.0:

`research/config/cbrc_public_real_sources.json`

The upstream archive, byte size, SHA-256, scene identifiers, and attribution source are pinned by the campaign. Scene imagery or derivatives used in publications must retain the applicable attribution.

### Deep Blending

The public v2.1 campaign also uses Dr Johnson and Playroom data from the Deep Blending members distributed in the pinned GraphDECO input bundle.

The MAVEB source manifest intentionally does not assign a blanket repository license to these scenes. It records them for research/evaluation under the upstream terms with attribution preserved.

Before redistributing scene-bearing figures, supplementary media, or publication material, verify the current upstream usage conditions and preserve the source documentation required by the target publisher.

## Public trained 3DGS validation source

The trained-3DGS validation fetches a pinned external PLY from:

```text
repo: camenduru/gaussian-splatting
revision: 5c74895a5bd96d6593d916407f102cff86d2ef45
file: train/point_cloud/iteration_30000/point_cloud.ply
SHA-256: f03e4979ac27345da1422d960d604b98db9541bdb3586d135d64bb4d9bde8eb3
```

The PLY is used as an external validation input and is not redistributed by MAVEB. The fetch step records the source host's reported license metadata in `TRAINED_3DGS_SOURCE.json`.

Derived paper figures and GIFs do not transfer ownership of the upstream trained representation to the MAVEB project. Preserve upstream attribution and terms.
