# Clustered lighting contract

AETHER uses a bounded forward-clustered light list rather than recompiling material pipelines for
different light counts. The default grid is 16 columns, 9 rows, and 24 logarithmic depth slices
from the active camera near plane to its finite working far depth. Directional lights occupy every
cluster. Point and spot lights use conservative projected range-sphere bounds and depth ranges.

The public light model distinguishes directional, point, and spot lights. Positions, directions,
linear RGB colors, intensity, range, and cone angles are validated for finiteness and physical
domain constraints. The renderer requires at least one light and uploads immutable snapshots per
frame. Cluster entries contain offsets and counts into a packed light-index list.

Cluster construction is deterministic. A configured reference budget is a hard limit: overflow
returns `resourceExhausted` and does not emit a partial list or silently discard lights. GPU upload
allocation failures also skip the incomplete frame with a structured log entry.

The PBR fragment stage derives its cluster from pixel coordinates and camera-space logarithmic
depth. It evaluates the cluster's directional, point, and spot lights using the existing GGX
metallic-roughness BRDF. Local lights use a smooth finite-range window with inverse-square-like
falloff; spot lights additionally apply inner/outer cone attenuation.

Tests cover exact grid sizing, complete directional assignment, finite local-light culling,
overflow rejection, invalid ranges, public renderer light validation, shader compilation, and a
live textured scene under Metal API validation. Light editor persistence, GPU cluster generation,
cluster visualization, IBL, and shadow maps remain later gates.
