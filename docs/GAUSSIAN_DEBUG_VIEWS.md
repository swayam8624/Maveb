# Gaussian debug views

Studio exposes seven stable Gaussian view modes: appearance, logarithmic depth, source ID, tile
occupancy, accumulated opacity, SH bands, and sort rank. All modes run through the production
projection/sort/composite path and therefore visualize the data that actually contributes to the
presented pixel.

SH Bands colors the dominant contributor by the highest stored spherical-harmonic degree: blue for
degree 0, green for degree 1, amber for degree 2, and red for degree 3. It describes coefficient
availability, not the magnitude of a particular band's evaluated contribution.

Sort Rank colors the dominant contributor by its normalized front-to-back position inside the
pixel's tile range. Blue is near the front and red is near the back. The rank is tile-local because
the renderer intentionally builds independent sorted ranges per tile.

The Metal integration fixture checks both views on a known degree-1 Gaussian under API and shader
validation. Ellipsoid wireframes require a dedicated instanced debug draw, while cluster views
depend on the Phase 7 hierarchy; neither is approximated from unrelated data.
