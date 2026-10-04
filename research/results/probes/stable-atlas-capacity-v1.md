# Stable Atlas Capacity Probe v1

The current fixed-capacity stable atlas fixes **address churn**, but this analytical stress probe
shows it does not scale to large persistent worlds as a single global texture.

At an 8192×8192 atlas with a 4-pixel gutter:

| reserved triangle slots | cell | inner tile | approx triangle texels |
|---:|---:|---:|---:|
| 10,000 | 81 px | 73 px | 2,664.5 |
| 50,000 | 36 px | 28 px | 392 |
| 100,000 | 25 px | 17 px | 144.5 |
| 250,000 | 16 px | 8 px | 32 |
| 500,000 | 11 px | 3 px | 4.5 |
| 750,000 | 9 px | 1 px | invalid by current contract |
| 1,000,000 | 8 px | 0 px | invalid |

Overprovisioning is especially costly. Reserving 100,000 slots for a 10,000-triangle active mesh
drops nominal per-triangle texel area to **5.4%** of the active-count layout; reserving 250,000 slots
for 100,000 active triangles leaves about **22.1%**.

This is not a rendered-quality result, but it is enough to reject one design assumption:

> A single globally fixed-capacity atlas is not a scalable solution to texture-address stability.

## Decision

**PARTIAL SURVIVOR, ARCHITECTURE PIVOT REQUIRED.**

Keep stable addressing as a required S1 subsystem, but do not promote the current global fixed-grid
layout as the long-term implementation. The next implementation candidate should add an indirection
that lets capacity grow without moving existing addresses: persistent pages/tiles, sparse residency,
or an equivalent page table. The existing stable-atlas branch remains useful as a correctness
fixture for slot stability at small/medium capacities.

Any paged design must measure:
- address survival under insertion/removal,
- page fragmentation,
- allocated/resident bytes,
- texel density,
- dirty page count,
- update bytes,
- render binding/lookup cost,
- compaction cost and whether compaction invalidates historical revisions.

Source commit: `359cfa5504cd68de6e3e16272a74403a57eaa6af`.
